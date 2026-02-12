#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-check}"
shift || true

case "$cmd" in
  check)
    if command -v tesseract >/dev/null 2>&1; then
      echo "LOCAL_VISION_OK:tesseract"
    else
      echo "LOCAL_VISION_OK:metadata-only"
    fi
    ;;
  image)
    f="${1:-}"
    [ -f "$f" ] || { echo "usage: $0 image <path>" >&2; exit 2; }
    echo "file=$f"
    file "$f" || true
    if command -v identify >/dev/null 2>&1; then identify "$f" || true; fi
    if command -v tesseract >/dev/null 2>&1; then
      tesseract "$f" stdout 2>/dev/null | sed -n '1,40p'
    else
      echo "OCR_UNAVAILABLE"
    fi
    ;;
  pdf)
    f="${1:-}"
    [ -f "$f" ] || { echo "usage: $0 pdf <path>" >&2; exit 2; }
    if command -v pdftotext >/dev/null 2>&1; then
      pdftotext "$f" - | sed -n '1,80p'
    else
      echo "PDF_TEXT_UNAVAILABLE"
    fi
    ;;
  *)
    echo "usage: $0 {check|image <path>|pdf <path>}" >&2
    exit 2
    ;;
esac
