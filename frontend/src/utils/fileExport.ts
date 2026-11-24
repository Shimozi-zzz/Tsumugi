export interface SaveDialogOptions {
  description: string
  mimeType: string
  ext: string
  pywebviewFileTypes: string[]
}

export interface SaveDialogResult {
  cancelled: boolean
  filename: string
  path?: string
  size_bytes: number
  fallbackDownload?: boolean
}

function sanitizeExportFilename(raw: string, ext: string): string {
  const cleanExt = ext.startsWith('.') ? ext : `.${ext}`
  const trimmed = (raw || 'tsumugi-export')
    .replace(/[<>:"/\\|?*\x00-\x1f]+/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^[._ ]+|[._ ]+$/g, '')
  const base = trimmed || 'tsumugi-export'
  return base.toLowerCase().endsWith(cleanExt.toLowerCase()) ? base : `${base}${cleanExt}`
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const commaIdx = result.indexOf(',')
      if (commaIdx < 0) {
        reject(new Error('文件编码转换失败'))
        return
      }
      resolve(result.slice(commaIdx + 1))
    }
    reader.onerror = () => reject(reader.error || new Error('读取导出数据失败'))
    reader.readAsDataURL(blob)
  })
}

function extractBasename(filePath: string, fallback: string): string {
  const parts = (filePath || '').split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || fallback
}

/**
 * 弹出保存文件对话框并落盘导出：
 * 1. 桌面端（PyWebView）：调用原生保存对话框并用 write_export_file 直写指定路径；
 * 2. Web 开发端（Chromium 等）：优先使用 File System Access API showSaveFilePicker；
 * 3. 若环境不支持保存对话框，回退至标准浏览器下载。
 */
export async function saveBlobWithDialog(
  blob: Blob,
  defaultFilename: string,
  opts: SaveDialogOptions,
): Promise<SaveDialogResult> {
  const safeName = sanitizeExportFilename(defaultFilename, opts.ext)
  const bridge = window.pywebview?.api

  // 1. 桌面端原生另存为弹窗 + 直写
  if (bridge?.select_save_file_path && bridge?.write_export_file) {
    const chosenPath = await bridge.select_save_file_path(
      safeName,
      opts.pywebviewFileTypes,
      opts.ext,
    )
    if (!chosenPath) {
      return { cancelled: true, filename: safeName, size_bytes: 0 }
    }
    const b64 = await blobToBase64(blob)
    const writeRes = await bridge.write_export_file(chosenPath, b64)
    if (!writeRes?.saved) {
      throw new Error(writeRes?.detail || '写入导出文件失败')
    }
    const savedPath = writeRes.path || chosenPath
    return {
      cancelled: false,
      filename: extractBasename(savedPath, safeName),
      path: savedPath,
      size_bytes: writeRes.size_bytes ?? blob.size,
    }
  }

  // 2. Web 开发端现代浏览器原生「另存为」选择器
  const savePicker = (
    window as Window & {
      showSaveFilePicker?: (options?: {
        suggestedName?: string
        types?: Array<{ description?: string; accept: Record<string, string[]> }>
      }) => Promise<{
        name?: string
        createWritable: () => Promise<{
          write: (data: Blob) => Promise<void>
          close: () => Promise<void>
        }>
      }>
    }
  ).showSaveFilePicker

  if (typeof savePicker === 'function') {
    try {
      const handle = await savePicker({
        suggestedName: safeName,
        types: [
          {
            description: opts.description,
            accept: {
              [opts.mimeType]: [opts.ext.startsWith('.') ? opts.ext : `.${opts.ext}`],
            },
          },
        ],
      })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
      return {
        cancelled: false,
        filename: handle.name || safeName,
        size_bytes: blob.size,
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return { cancelled: true, filename: safeName, size_bytes: 0 }
      }
      // 非用户取消错误时允许继续走普通下载兜底
    }
  }

  // 3. 回退浏览器标准下载
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = safeName
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1500)
  }
  return {
    cancelled: false,
    filename: safeName,
    size_bytes: blob.size,
    fallbackDownload: true,
  }
}
