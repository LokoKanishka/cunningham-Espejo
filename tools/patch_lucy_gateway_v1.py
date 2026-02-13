#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


CODE_JS = r'''
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function isObject(v) {
  return v && typeof v === 'object' && !Array.isArray(v);
}

function normalizeCorrelationId(rawBody) {
  const cid = rawBody.correlation_id;
  if (typeof cid === 'string' && cid.length >= 8 && cid.length <= 128) {
    return cid;
  }
  const payloadHash = crypto.createHash('sha256').update(JSON.stringify(rawBody)).digest('hex').slice(0, 24);
  return `cid_${payloadHash}`;
}

const body = isObject($json.body) ? $json.body : {};
const headers = isObject($json.headers) ? $json.headers : {};
const receivedTs = new Date().toISOString();
const correlationId = normalizeCorrelationId(body);

const inboxDir = '/data/lucy_ipc/inbox';
const deadletterDir = '/data/lucy_ipc/deadletter';

const sourceIp = headers['x-forwarded-for'] || headers['x-real-ip'] || $json.ip || '';
const subset = {
  'user-agent': headers['user-agent'] || '',
  'content-type': headers['content-type'] || '',
  'x-request-id': headers['x-request-id'] || ''
};

const envelope = {
  version: 'v1',
  correlation_id: correlationId,
  received_ts: receivedTs,
  payload: body,
  headers_subset: subset,
  source_ip: sourceIp,
  status: 'accepted'
};

const errors = [];
if (typeof body.kind !== 'string' || !body.kind.trim()) errors.push('kind is required string');
if (typeof body.source !== 'string' || !body.source.trim()) errors.push('source is required string');
if (typeof body.ts !== 'string' || Number.isNaN(Date.parse(body.ts))) errors.push('ts must be RFC3339 date-time');
if (Object.prototype.hasOwnProperty.call(body, 'text') && typeof body.text !== 'string') errors.push('text must be string');
if (Object.prototype.hasOwnProperty.call(body, 'meta') && !isObject(body.meta)) errors.push('meta must be object');

const inboxPath = path.join(inboxDir, `${correlationId}.json`);
const deadletterPath = path.join(deadletterDir, `${correlationId}.json`);

let ack = {
  ok: true,
  correlation_id: correlationId,
  received_ts: receivedTs,
  status: 'accepted',
  next: `ipc://inbox/${correlationId}.json`
};

try {
  fs.mkdirSync(inboxDir, { recursive: true });
  fs.mkdirSync(deadletterDir, { recursive: true });

  if (fs.existsSync(inboxPath)) {
    envelope.status = 'duplicate';
    ack.next = `ipc://inbox/${correlationId}.json`;
  } else if (errors.length > 0) {
    envelope.status = 'deadletter';
    envelope.reason = `invalid_contract: ${errors.join('; ')}`;
    fs.writeFileSync(deadletterPath, JSON.stringify(envelope, null, 2) + '\n', { encoding: 'utf-8' });
    ack.ok = false;
    ack.reason = envelope.reason;
    ack.next = `ipc://deadletter/${correlationId}.json`;
  } else {
    fs.writeFileSync(inboxPath, JSON.stringify(envelope, null, 2) + '\n', { encoding: 'utf-8' });
  }
} catch (err) {
  const reason = `ipc_write_failed: ${err && err.message ? err.message : String(err)}`;
  envelope.status = 'deadletter';
  envelope.reason = reason;
  ack.ok = false;
  ack.reason = reason;
  ack.next = `ipc://deadletter/${correlationId}.json`;
  try {
    fs.mkdirSync(deadletterDir, { recursive: true });
    fs.writeFileSync(deadletterPath, JSON.stringify(envelope, null, 2) + '\n', { encoding: 'utf-8' });
  } catch (_) {
    // keep ACK deterministic even when deadletter write fails
  }
}

return [{ json: ack }];
'''.strip()


def ensure_workflow(obj):
    if isinstance(obj, list):
        if not obj:
            raise SystemExit("empty workflow list")
        return obj[0], True
    return obj, False


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: patch_lucy_gateway_v1.py <input.json> <output.json>", file=sys.stderr)
        return 2

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])

    raw = json.loads(src.read_text(encoding="utf-8"))
    wf, wrapped = ensure_workflow(raw)

    nodes = wf.get("nodes") or []

    webhook = None
    for node in nodes:
        if node.get("type") == "n8n-nodes-base.webhook":
            webhook = node
            break

    if webhook is None:
        raise SystemExit("workflow does not contain required webhook node")

    code_name = "Gateway Contract + IPC"
    code_node = {
        "parameters": {
            "mode": "runOnceForAllItems",
            "jsCode": CODE_JS,
        },
        "id": "lucy-gateway-code-v1",
        "name": code_name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [800, 300],
    }

    remove_names = {
        code_name,
        "Gateway Prepare v1",
        "Gateway IPC Writer v1",
        "Gateway ACK v1",
    }
    remove_types = {
        "n8n-nodes-base.respondToWebhook",
        "n8n-nodes-base.executeCommand",
    }
    clean_nodes = [
        n for n in nodes
        if n.get("name") not in remove_names and n.get("type") not in remove_types
    ]
    clean_nodes.append(code_node)

    webhook_name = webhook["name"]
    webhook_params = webhook.get("parameters") or {}
    webhook_params["responseMode"] = "lastNode"
    webhook["parameters"] = webhook_params

    wf["nodes"] = clean_nodes
    wf["connections"] = {
        webhook_name: {
            "main": [[{"node": code_name, "type": "main", "index": 0}]],
        },
    }

    out_obj = [wf] if wrapped else wf
    dst.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PATCH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
