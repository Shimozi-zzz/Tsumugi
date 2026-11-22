/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

interface PyWebviewAPI {
  pick_file?: (title?: string, fileTypes?: string[]) => Promise<string>
  pick_folder?: (title?: string) => Promise<string>
  resolve_dropped_path?: (rawPath: string) => Promise<{
    kind: string
    folder_path: string
    exe_path: string
    suggested_title: string
  }>
  minimize_to_tray?: () => Promise<boolean>
  quit_app?: () => Promise<void>
}

interface Window {
  pywebview?: {
    api?: PyWebviewAPI
  }
}
