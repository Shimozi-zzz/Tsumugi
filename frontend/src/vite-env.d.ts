/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}

type DesktopWindowMode = 'normal' | 'maximized' | 'fullscreen'
type DesktopResizeEdge =
  | 'left'
  | 'right'
  | 'top'
  | 'bottom'
  | 'top-left'
  | 'top-right'
  | 'bottom-left'
  | 'bottom-right'

interface DesktopWindowState {
  is_desktop: boolean
  mode?: DesktopWindowMode
  is_fullscreen: boolean
  is_maximized: boolean
}

interface PyWebviewAPI {
  minimize?: () => Promise<boolean>
  toggle_maximize?: () => Promise<boolean>
  start_drag?: (cursorRatioX?: number) => Promise<boolean>
  start_resize?: (edge: DesktopResizeEdge) => Promise<boolean>
  restore_for_drag?: (ratioX?: number) => Promise<boolean>
  toggle_fullscreen?: () => Promise<boolean>
  exit_fullscreen?: () => Promise<boolean>
  close?: () => Promise<boolean>
  get_window_state?: () => Promise<DesktopWindowState>
  pick_file?: (title?: string, fileTypes?: string[]) => Promise<string>
  pick_folder?: (title?: string) => Promise<string>
  select_backup_save_path?: (defaultName?: string) => Promise<string>
  select_backup_open_path?: () => Promise<string>
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
