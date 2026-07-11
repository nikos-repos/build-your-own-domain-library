---
name: glmocr
description:
  Extract text from images using GLM-OCR API. Supports images and PDFs with
  high accuracy OCR, table recognition, formula extraction, and handwriting recognition.
  Use this skill whenever the user wants to extract text from images, perform OCR on
  pictures, scan documents, convert images to text, or process any image files to get
  their textual content.
metadata:
  openclaw:
    requires:
      env:
        - ZHIPU_API_KEY
        - GLM_OCR_TIMEOUT
      bins:
        - python
    primaryEnv: ZHIPU_API_KEY
    emoji: "📄"
    homepage: https://github.com/zai-org/GLM-OCR/tree/main/agents/skills/glmocr
---

# GLM-OCR Text Extraction Skill

Extract text from images and PDFs using the GLM-OCR layout parsing API.

## When to Use

- Process scanned documents
- Recognize tables and formulas in documents
- User mentions "OCR"

## Key Features

- **Table recognition**: Detects and converts tables to Markdown format
- **Formula extraction**: LaTeX format output
- **Local file & URL**: Supports local files and remote URLs

## Resource Links

| Resource | Link                               |
| -------- | ---------------------------------- |
| GitHub   | https://github.com/zai-org/GLM-OCR |

**⛔ MANDATORY RESTRICTIONS - DO NOT VIOLATE ⛔**

1. **ONLY use GLM-OCR API** - Execute the script `python scripts/glm_ocr_cli.py`
2. **NEVER parse documents directly** - Do NOT try to extract text yourself
3. **NEVER offer alternatives** - Do NOT suggest "I can try to analyze it" or similar
4. **IF API fails** - Display the error message and STOP immediately
5. **NO fallback methods** - Do NOT attempt text extraction any other way



### Extract from URL

```bash
python scripts/glm_ocr_cli.py --file-url "URL provided by user"
```

### Extract from Local File

```bash
python scripts/glm_ocr_cli.py --file /path/to/image.jpg
```

### Save result to file (recommended)

```bash
python scripts/glm_ocr_cli.py --file-url "URL" --output result.json
```

### PDFs over 100 pages / 50MB

The GLM-OCR API rejects PDFs over 100 pages and PDFs over 50MB. For long books, split into chunks that satisfy **both** limits: `<=100 pages` and `<50MB` OCR each chunk with `--return-crop-images`, then concatenate `text` and flatten `layout_details` into `combined.json`. Download crop-image URLs immediately into `glmocr_output/imgs/` and rewrite image regions with `image_path: imgs/<file>` before fidelity reconstruction.

Use`pypdf` range writing for resumable chunks; verify `stat().st_size < 50MB` before each API call. If an existing chunk JSON has `ok:false`, do not skip it as completed.

```bash
python scripts/glm_ocr_cli.py --file book-pages-001-100.pdf --return-crop-images --output part-001-100.json --pretty
```

## CLI Reference

```
python {baseDir}/scripts/glm_ocr_cli.py (--file-url URL | --file PATH) [--output FILE] [--pretty] [--start-page-id N] [--end-page-id N] [--return-crop-images]
```

| Parameter              | Required | Description                                      |
| ---------------------- | -------- | ------------------------------------------------ |
| `--file-url`           | One of   | URL to image/PDF                                 |
| `--file`               | One of   | Local file path to image/PDF                     |
| `--output`, `-o`       | No       | Save result JSON to file                         |
| `--pretty`             | No       | Pretty-print JSON output                         |
| `--start-page-id`      | No       | First PDF page to process when API accepts range |
| `--end-page-id`        | No       | Last PDF page to process when API accepts range  |
| `--return-crop-images` | No       | Return crop-image URLs for figures/charts        |

## Response Format

```json
{
  "ok": true,
  "text": "# Extracted text in Markdown...",
  "layout_details": [[...]],
  "result": { "raw_api_response": "..." },
  "error": null,
  "source": "/path/to/file.jpg",
  "source_type": "file"
}
```

Key fields:

- `ok` — whether extraction succeeded
- `text` — extracted text in Markdown (use this for display)
- `layout_details` — layout analysis details
- `result` — raw API response
- `error` — error details on failure

## Error Handling

**API key not configured:**

```
Error: ZHIPU_API_KEY not configured. Get your API key at: https://www.bigmodel.cn/usercenter/proj-mgmt/apikeys
```

→ Show exact error to user, guide them to configure

**Authentication failed (401/403):** API key invalid/expired → reconfigure

**Rate limit (429):** Quota exhausted → inform user to wait

**File not found:** Local file missing → check path

## Reference

- `references/output_schema.md` — detailed output format specification
