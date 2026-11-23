/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

interface PyWebviewAPI {
  minimize?: () => Promise<boolean>
  toggle_maximize?: () => Promise<boolean>
  start_drag?: (cursorRatioX?: number) => Promise<boolean>
  restore_for_drag?: (ratioX?: number) => Promise<boolean>
  toggle_fullscreen?: () => Promise<boolean>
  exit_fullscreen?: () => Promise<boolean>
  close?: () => Promise<boolean>
  get_window_state?: () => Promise<{
    is_desktop: boolean
    is_fullscreen: boolean
    is_maximized: boolean
  }>
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
