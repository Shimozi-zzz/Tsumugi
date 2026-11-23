<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  assetUrl,
  isDesktopBridgeAvailable,
  mediaApi,
  musicPreviewUrl,
  pickNativeFile,
  pickNativeFolder,
  scraperApi,
} from '@/api/client'
import AssetPickerModal from '@/components/AssetPickerModal.vue'
import MetadataPickerModal from '@/components/MetadataPickerModal.vue'
import { PAUSE_MEDIA_EVENT, useAudioStore } from '@/stores/audio'
import { useLibraryStore } from '@/stores/library'
import { useTaskStore } from '@/stores/tasks'
import type {
  Game,
  MetadataApplyPatch,
  MetadataFieldKey,
  MusicCandidate,
  PickerAssetType,
} from '@/types'
import { normalizePlatformBadge, PLATFORM_OPTIONS } from '@/utils/platform'

const store = useLibraryStore()
const audioStore = useAudioStore()
const taskStore = useTaskStore()
const game = computed(() => store.activeGame)
const tab = ref<'meta' | 'media' | 'launch'>(store.editInitialTab || 'meta')
const saving = ref(false)
const mediaActionBusy = ref(false)
const uploadingType = ref<string>('')
const confirmDelete = ref(false)
const hasBridge = isDesktopBridgeAvailable()

const initial = game.value
const form = reactive({
  title: initial?.title || '',
  sub_title: initial?.sub_title || '',
  developer: initial?.developer || '',
  publisher: initial?.publisher || '',
  release_date: initial?.release_date || '',
  synopsis: initial?.synopsis || '',
  tags: [...(initial?.tags || [])].filter(Boolean),
  status: initial?.status || 'todo',
  is_nsfw: Boolean(initial?.is_nsfw),
  source_platform: normalizePlatformBadge(initial?.source_platform, initial?.external_ids),
  bangumi_id: initial?.bangumi_id || initial?.external_ids?.bgm || '',
  series: initial?.series || '',
  locked_fields: [...(initial?.locked_fields || [])],
  media: {
    pv_url_or_path: initial?.media?.pv_url_or_path || '',
    bgm_path: initial?.media?.bgm_path || '',
    exe_path: initial?.media?.exe_path || '',
    launch_mode: initial?.media?.launch_mode || 'direct',
    launch_args: initial?.media?.launch_args || '',
    save_dir: initial?.media?.save_dir || '',
    screenshot_dir: initial?.media?.screenshot_dir || '',
  },
})

// Tag Chips 编辑器状态
const tagDraft = ref('')
const tagInputRef = ref<HTMLInputElement | null>(null)

function commitTagDraft() {
  const raw = tagDraft.value.trim()
  if (!raw) {
    tagDraft.value = ''
    return
  }
  const parts = raw
    .split(/[,，\n]/)
    .map((p) => p.trim())
    .filter(Boolean)
  for (const part of parts) {
    if (!form.tags.includes(part)) {
      form.tags.push(part)
    }
  }
  tagDraft.value = ''
}

function handleTagKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' || ev.key === ',' || ev.key === '，') {
    ev.preventDefault()
    commitTagDraft()
  } else if (ev.key === 'Backspace' && !tagDraft.value && form.tags.length > 0) {
    form.tags.pop()
  }
}

function handleTagInput() {
  if (/[,，]/.test(tagDraft.value)) {
    commitTagDraft()
  }
}

function removeTag(tag: string) {
  form.tags = form.tags.filter((t) => t !== tag)
}

function focusTagInput() {
  tagInputRef.value?.focus()
}

// 在线 OP 原声搜寻与试听状态
const musicQuery = ref((initial?.sub_title || initial?.title || '').trim())
const musicSearching = ref(false)
const musicSearchedOnce = ref(false)
const musicCandidates = ref<MusicCandidate[]>([])
const musicDownloadingId = ref<string>('')
const previewingId = ref<string>('')
let previewAudio: HTMLAudioElement | null = null

function stopPreviewAudio() {
  if (previewAudio) {
    previewAudio.pause()
    previewAudio.src = ''
    previewAudio = null
  }
  previewingId.value = ''
}

const musicSource = ref<'auto' | 'bilibili' | 'youtube' | 'itunes'>('auto')
const MUSIC_SOURCES: { key: 'auto' | 'bilibili' | 'youtube' | 'itunes'; label: string }[] = [
  { key: 'auto', label: '自动' },
  { key: 'bilibili', label: 'Bilibili' },
  { key: 'youtube', label: 'YouTube' },
  { key: 'itunes', label: 'iTunes' },
]

async function searchOnlineMusic(overrideSource?: 'auto' | 'bilibili' | 'youtube' | 'itunes') {
  if (overrideSource) {
    musicSource.value = overrideSource
  }
  const q = musicQuery.value.trim()
  if (!q || musicSearching.value) return
  stopPreviewAudio()
  musicSearching.value = true
  musicSearchedOnce.value = true
  try {
    const altTitle =
      q !== (form.title || '').trim()
        ? (form.title || '').trim()
        : (form.sub_title || '').trim()
    const res = await scraperApi.searchMusic(q, {
      source: musicSource.value,
      alt_title: altTitle,
    })
    musicCandidates.value = res.items
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '原声搜寻失败', 'warning')
    musicCandidates.value = []
  } finally {
    musicSearching.value = false
  }
}

function togglePreviewCandidate(item: MusicCandidate) {
  if (previewingId.value === item.id) {
    stopPreviewAudio()
    return
  }
  stopPreviewAudio()
  void audioStore.stopSmooth()

  const playSrc = item.preview_url ? item.preview_url : musicPreviewUrl(item.source_url)
  const el = new Audio(playSrc)
  el.volume = 0.7
  previewAudio = el
  previewingId.value = item.id

  el.addEventListener('ended', () => {
    if (previewingId.value === item.id) previewingId.value = ''
  })
  el.addEventListener('error', () => {
    if (previewingId.value === item.id) {
      previewingId.value = ''
      store.notify('该候选音频暂无法直接试听，可尝试直接下载绑定', 'warning')
    }
  })

  void el.play().catch(() => {
    if (previewingId.value === item.id) previewingId.value = ''
  })
}

async function downloadCandidate(item: MusicCandidate, mode: 'link_only' | 'download' = 'download') {
  if (!game.value || musicDownloadingId.value) return
  stopPreviewAudio()
  musicDownloadingId.value = `${item.id}:${mode}`
  try {
    const res = await scraperApi.downloadMusic(game.value.id, {
      source_url: item.source_url,
      preview_url: item.preview_url,
      mode,
      async_mode: mode === 'download',
    })
    form.media.bgm_path = res.bgm_path
    const fresh = await store.refreshGame(game.value.id)
    if (mode === 'download' && res.download_task) {
      taskStore.trackTask(res.download_task)
      store.notify(`已加入后台下载主题曲《${item.title}》，期间可直接在线播放`, 'info')
    } else if (mode === 'link_only') {
      taskStore.dismissTask(game.value.id, 'bgm')
      if (fresh) {
        void audioStore.syncGameBgm(fresh, { autoPlay: false, cacheBust: store.assetVersion })
      }
      store.notify(`已保存主题曲在线链接《${item.title}》`, 'success')
    } else {
      if (fresh) {
        void audioStore.syncGameBgm(fresh, { autoPlay: false, cacheBust: store.assetVersion })
      }
      store.notify(`已下载并绑定原声《${item.title}》`, 'success')
    }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '保存主题曲失败', 'error')
  } finally {
    musicDownloadingId.value = ''
  }
}

function formatSec(sec: number): string {
  if (!sec || sec <= 0) return '—'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function isInCollection(collectionId: number): boolean {
  if (!game.value) return false
  const col = store.collections.find((c) => c.id === collectionId)
  return Boolean(col?.game_ids.includes(game.value.id))
}

async function handleToggleCollection(collectionId: number) {
  if (!game.value) return
  try {
    await store.toggleGameInCollection(collectionId, game.value.id)
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '更新分组归属失败', 'error')
  }
}

function isLocked(field: string): boolean {
  return form.locked_fields.includes(field)
}

function toggleLock(field: string) {
  if (isLocked(field)) {
    form.locked_fields = form.locked_fields.filter((f) => f !== field)
  } else {
    form.locked_fields.push(field)
  }
}

function lockTitle(field: string): string {
  return isLocked(field) ? '已锁定，重新刮削时保留当前值' : '点击锁定此字段'
}

async function handleUpload(
  assetType: 'cover' | 'logo' | 'hero' | 'custom_spine' | 'pv' | 'bgm',
  ev: Event,
) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !game.value) return
  uploadingType.value = assetType
  try {
    const res = await mediaApi.upload(game.value.id, assetType, file)
    if (assetType === 'pv') {
      form.media.pv_url_or_path = res.path
    } else if (assetType === 'bgm') {
      form.media.bgm_path = res.path
    }
    await store.refreshGame(game.value.id)
    store.notify(`已上传并更新 ${assetType} 资产`, 'success')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '资产上传失败', 'error')
  } finally {
    uploadingType.value = ''
    input.value = ''
  }
}

async function clearBgm() {
  stopPreviewAudio()
  form.media.bgm_path = ''
  if (game.value) {
    await store.updateGamePatch(game.value.id, {
      media: { bgm_path: '', bgm_remote_url: '', bgm_mode: 'none' },
    })
    taskStore.dismissTask(game.value.id, 'bgm')
    void audioStore.stopSmooth()
    store.notify('已清除该作品的绑定原声', 'info')
  }
}

function isHttpUrl(raw?: string | null): boolean {
  return /^https?:\/\//i.test((raw || '').trim())
}

const pvLocalActive = computed(() => {
  const v = (form.media.pv_url_or_path || '').trim()
  return Boolean(v && !isHttpUrl(v))
})
const pvRemoteUrl = computed(() => {
  const stored = (game.value?.media?.pv_remote_url || '').trim()
  if (isHttpUrl(stored)) return stored
  const typed = (form.media.pv_url_or_path || '').trim()
  return isHttpUrl(typed) ? typed : ''
})
const bgmLocalActive = computed(() => {
  const v = (form.media.bgm_path || '').trim()
  return Boolean(v && !isHttpUrl(v))
})
const bgmRemoteUrl = computed(() => {
  const stored = (game.value?.media?.bgm_remote_url || '').trim()
  if (isHttpUrl(stored)) return stored
  const typed = (form.media.bgm_path || '').trim()
  return isHttpUrl(typed) ? typed : ''
})

async function cacheRemoteMedia(assetType: 'pv' | 'bgm') {
  if (!game.value || mediaActionBusy.value) return
  const typedUrl = assetType === 'pv' ? form.media.pv_url_or_path.trim() : form.media.bgm_path.trim()
  const remote = assetType === 'pv' ? pvRemoteUrl.value : bgmRemoteUrl.value
  if (!remote) {
    store.notify(assetType === 'pv' ? '请先填写或查找在线宣传片链接' : '请先填写或查找在线主题曲链接', 'warning')
    return
  }
  mediaActionBusy.value = true
  try {
    // 若用户在输入框里刚粘贴了新链接尚未保存，先落库再触发下载
    if (isHttpUrl(typedUrl) && typedUrl !== (assetType === 'pv' ? game.value.media?.pv_remote_url : game.value.media?.bgm_remote_url)) {
      await store.updateGamePatch(game.value.id, {
        media:
          assetType === 'pv'
            ? { pv_url_or_path: typedUrl, pv_remote_url: typedUrl, pv_mode: 'link_only' }
            : { bgm_path: typedUrl, bgm_remote_url: typedUrl, bgm_mode: 'link_only' },
      })
    }
    const res = await mediaApi.cacheRemote(game.value.id, assetType)
    store.syncGameFromServer(res)
    if (assetType === 'pv') {
      form.media.pv_url_or_path = res.media?.pv_url_or_path || form.media.pv_url_or_path
      taskStore.trackTask(
        res.download_task || {
          game_id: game.value.id,
          asset_type: 'pv',
          status: 'queued',
          progress: 0,
          message: '等待下载宣传片…',
        },
        { url: remote },
      )
      store.notify('宣传片已加入后台下载，完成后自动切换本地播放', 'info')
    } else {
      form.media.bgm_path = res.media?.bgm_path || form.media.bgm_path
      taskStore.trackTask(
        res.download_task || {
          game_id: game.value.id,
          asset_type: 'bgm',
          status: 'queued',
          progress: 0,
          message: '等待下载主题曲…',
        },
      )
      store.notify('主题曲已加入后台下载，完成后自动切换本地播放', 'info')
    }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '触发本地下载失败', 'error')
  } finally {
    mediaActionBusy.value = false
  }
}

async function dropLocalCacheMedia(assetType: 'pv' | 'bgm') {
  if (!game.value || mediaActionBusy.value) return
  mediaActionBusy.value = true
  try {
    const updated = await mediaApi.dropLocalCache(game.value.id, assetType)
    store.syncGameFromServer(updated)
    if (assetType === 'pv') {
      form.media.pv_url_or_path = updated.media?.pv_url_or_path || ''
      store.notify(
        updated.media?.pv_remote_url
          ? '已删除本地视频缓存，保留在线链接可直接播放'
          : '已删除本地视频文件',
        'success',
      )
    } else {
      form.media.bgm_path = updated.media?.bgm_path || ''
      void audioStore.syncGameBgm(updated, { autoPlay: false, cacheBust: store.assetVersion })
      store.notify(
        updated.media?.bgm_remote_url
          ? '已删除本地音频缓存，保留在线链接可直接播放'
          : '已删除本地音频文件',
        'success',
      )
    }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '删除本地缓存失败', 'error')
  } finally {
    mediaActionBusy.value = false
  }
}

async function pickPath(field: 'exe_path' | 'save_dir' | 'screenshot_dir') {
  if (field === 'exe_path') {
    const p = await pickNativeFile('选择游戏主程序 (.exe / .lnk)')
    if (p) form.media.exe_path = p
  } else {
    const p = await pickNativeFolder(field === 'save_dir' ? '选择存档目录' : '选择截图目录')
    if (p) form.media[field] = p
  }
}

async function save() {
  if (!game.value || !form.title.trim()) return
  commitTagDraft()
  saving.value = true
  try {
    await store.updateGamePatch(game.value.id, {
      title: form.title.trim(),
      sub_title: form.sub_title.trim(),
      developer: form.developer.trim(),
      publisher: form.publisher.trim(),
      release_date: form.release_date.trim(),
      synopsis: form.synopsis.trim(),
      tags: [...form.tags],
      status: form.status,
      is_nsfw: form.is_nsfw,
      source_platform: form.source_platform,
      bangumi_id: form.bangumi_id.trim(),
      series: form.series.trim(),
      locked_fields: form.locked_fields,
      media: {
        pv_url_or_path: form.media.pv_url_or_path.trim(),
        bgm_path: form.media.bgm_path.trim(),
        exe_path: form.media.exe_path.trim(),
        launch_mode: form.media.launch_mode,
        launch_args: form.media.launch_args.trim(),
        save_dir: form.media.save_dir.trim(),
        screenshot_dir: form.media.screenshot_dir.trim(),
      },
    })
    store.notify('游戏信息已保存', 'success')
    store.showEditModal = false
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function removeGame() {
  if (!game.value) return
  if (!confirmDelete.value) {
    confirmDelete.value = true
    return
  }
  await store.deleteGameById(game.value.id)
  store.showEditModal = false
}

const pickerAssetType = ref<PickerAssetType | null>(null)
const clearingAsset = ref<string>('')
const showMetadataPicker = ref(false)
const metadataFocusField = ref<MetadataFieldKey | null>(null)
const pvTask = computed(() => taskStore.getTask(game.value?.id, 'pv'))
const bgmTask = computed(() => taskStore.getTask(game.value?.id, 'bgm'))

onMounted(() => {
  store.editInitialTab = 'meta'
})

function openMetadataPicker(focus: MetadataFieldKey | null = null) {
  metadataFocusField.value = focus
  showMetadataPicker.value = true
}

function handleMetadataApplied(patch: MetadataApplyPatch) {
  let count = 0
  if (patch.title !== undefined) {
    form.title = patch.title
    count++
  }
  if (patch.sub_title !== undefined) {
    form.sub_title = patch.sub_title
    count++
  }
  if (patch.developer !== undefined) {
    form.developer = patch.developer
    count++
  }
  if (patch.publisher !== undefined) {
    form.publisher = patch.publisher
    count++
  }
  if (patch.release_date !== undefined) {
    form.release_date = patch.release_date
    count++
  }
  if (patch.bangumi_id !== undefined) {
    form.bangumi_id = patch.bangumi_id
    count++
  }
  if (patch.tags !== undefined) {
    if (patch.tagsMode === 'merge') {
      const merged = [...form.tags]
      for (const t of patch.tags) {
        if (t && !merged.includes(t)) merged.push(t)
      }
      form.tags = merged
    } else {
      form.tags = [...patch.tags]
    }
    count++
  }
  if (patch.description !== undefined) {
    form.synopsis = patch.description
    count++
  }
  showMetadataPicker.value = false
  if (count > 0) {
    store.notify(`已将 ${count} 项资料填入表单`, 'info')
  }
}

watch(
  () => game.value?.media?.pv_url_or_path,
  (nextPath) => {
    if (nextPath !== undefined && nextPath !== form.media.pv_url_or_path) {
      form.media.pv_url_or_path = nextPath
    }
  },
)

watch(
  () => game.value?.media?.bgm_path,
  (nextPath) => {
    if (nextPath !== undefined && nextPath !== form.media.bgm_path) {
      form.media.bgm_path = nextPath
    }
  },
)

function openAssetPicker(assetType: PickerAssetType) {
  pickerAssetType.value = assetType
}

function handleAssetApplied(updated: Game) {
  if (pickerAssetType.value === 'pv') {
    form.media.pv_url_or_path = updated.media?.pv_url_or_path || ''
  }
  pickerAssetType.value = null
}

async function clearVisualAsset(assetType: 'cover' | 'logo' | 'hero' | 'custom_spine') {
  if (!game.value || clearingAsset.value) return
  clearingAsset.value = assetType
  try {
    const patch =
      assetType === 'cover'
        ? { cover_path: '', cover_thumb_path: '' }
        : assetType === 'logo'
          ? { logo_path: '' }
          : assetType === 'hero'
            ? { hero_bg_path: '' }
            : { custom_spine_path: '' }
    await store.updateGamePatch(game.value.id, { media: patch })
    store.notify('已清除该图片资产', 'info')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '清除失败', 'error')
  } finally {
    clearingAsset.value = ''
  }
}

const assetCards = computed(() => {
  const m = game.value?.media
  return [
    {
      key: 'cover' as const,
      pickerKey: 'cover' as const,
      label: '封面原图',
      preview: m?.cover_path ? assetUrl(m.cover_path, store.assetVersion) : '',
      accept: 'image/*',
    },
    {
      key: 'logo' as const,
      pickerKey: 'logo' as const,
      label: '透明艺术字 Logo',
      preview: m?.logo_path ? assetUrl(m.logo_path, store.assetVersion) : '',
      accept: 'image/*',
    },
    {
      key: 'hero' as const,
      pickerKey: 'hero' as const,
      label: '宽幅 Hero 背景图',
      preview: m?.hero_bg_path ? assetUrl(m.hero_bg_path, store.assetVersion) : '',
      accept: 'image/*',
    },
    {
      key: 'custom_spine' as const,
      pickerKey: 'spine' as const,
      label: '自定义光盘盒侧封',
      preview: m?.custom_spine_path ? assetUrl(m.custom_spine_path, store.assetVersion) : '',
      accept: 'image/*',
    },
  ]
})

onMounted(() => {
  window.addEventListener(PAUSE_MEDIA_EVENT, stopPreviewAudio)
})

onBeforeUnmount(() => {
  window.removeEventListener(PAUSE_MEDIA_EVENT, stopPreviewAudio)
  stopPreviewAudio()
})
</script>

<template>
  <div v-if="game" class="modal-backdrop" @click.self="store.showEditModal = false">
    <div class="modal-card edit-card">
      <div class="modal-head">
        <div class="head-titles">
          <h2>{{ game.title }}</h2>
        </div>
        <button class="close-icon-btn" aria-label="关闭" @click="store.showEditModal = false">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <!-- 精致底边指示条 Tab 栏 -->
      <div class="edit-tabs" role="tablist">
        <button type="button" :class="{ active: tab === 'meta' }" @click="tab = 'meta'">
          基本信息
        </button>
        <button type="button" :class="{ active: tab === 'media' }" @click="tab = 'media'">
          视觉资产与原声
        </button>
        <button type="button" :class="{ active: tab === 'launch' }" @click="tab = 'launch'">
          启动与目录
        </button>
      </div>

      <div class="modal-body">
        <!-- Tab 1: 基本信息 -->
        <template v-if="tab === 'meta'">
          <section class="form-group">
            <div class="group-head-row">
              <h3 class="group-title">核心元数据</h3>
              <button
                type="button"
                class="meta-replace-btn"
                @click="openMetadataPicker(null)"
              >
                <svg viewBox="0 0 16 16" width="12.5" height="12.5" fill="none" stroke="currentColor" stroke-width="1.65">
                  <circle cx="7.2" cy="7.2" r="4.5" />
                  <path d="M10.7 10.7l3 3" stroke-linecap="round" />
                </svg>
                <span>在线替换资料</span>
              </button>
            </div>
            <div class="field-grid">
              <div class="field">
                <div class="label-row">
                  <label>主标题</label>
                  <button
                    type="button"
                    class="lock-icon-btn"
                    :class="{ locked: isLocked('title') }"
                    :title="lockTitle('title')"
                    @click="toggleLock('title')"
                  >
                    <svg v-if="isLocked('title')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                    </svg>
                    <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                    </svg>
                  </button>
                </div>
                <input v-model="form.title" class="input" />
              </div>

              <div class="field">
                <div class="label-row">
                  <label>原名 / 副标题</label>
                  <button
                    type="button"
                    class="lock-icon-btn"
                    :class="{ locked: isLocked('sub_title') }"
                    :title="lockTitle('sub_title')"
                    @click="toggleLock('sub_title')"
                  >
                    <svg v-if="isLocked('sub_title')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                    </svg>
                    <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                    </svg>
                  </button>
                </div>
                <input v-model="form.sub_title" class="input" />
              </div>
            </div>

            <div class="field-grid three">
              <div class="field">
                <div class="label-row">
                  <label>开发商</label>
                  <div class="field-tools">
                    <button
                      type="button"
                      class="field-search-btn"
                      title="在线查找并替换此项"
                      @click="openMetadataPicker('developer')"
                    >
                      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6">
                        <circle cx="7.2" cy="7.2" r="4.3" />
                        <path d="M10.5 10.5l2.8 2.8" stroke-linecap="round" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      class="lock-icon-btn"
                      :class="{ locked: isLocked('developer') }"
                      :title="lockTitle('developer')"
                      @click="toggleLock('developer')"
                    >
                      <svg v-if="isLocked('developer')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                      </svg>
                      <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                      </svg>
                    </button>
                  </div>
                </div>
                <input v-model="form.developer" class="input" />
              </div>

              <div class="field">
                <div class="label-row">
                  <label>发行商</label>
                  <div class="field-tools">
                    <button
                      type="button"
                      class="field-search-btn"
                      title="在线查找并替换此项"
                      @click="openMetadataPicker('publisher')"
                    >
                      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6">
                        <circle cx="7.2" cy="7.2" r="4.3" />
                        <path d="M10.5 10.5l2.8 2.8" stroke-linecap="round" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      class="lock-icon-btn"
                      :class="{ locked: isLocked('publisher') }"
                      :title="lockTitle('publisher')"
                      @click="toggleLock('publisher')"
                    >
                      <svg v-if="isLocked('publisher')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                      </svg>
                      <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                      </svg>
                    </button>
                  </div>
                </div>
                <input v-model="form.publisher" class="input" />
              </div>

              <div class="field">
                <div class="label-row">
                  <label>发售日期</label>
                  <button
                    type="button"
                    class="lock-icon-btn"
                    :class="{ locked: isLocked('release_date') }"
                    :title="lockTitle('release_date')"
                    @click="toggleLock('release_date')"
                  >
                    <svg v-if="isLocked('release_date')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                    </svg>
                    <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                    </svg>
                  </button>
                </div>
                <input v-model="form.release_date" class="input tabular-nums" placeholder="YYYY-MM-DD" />
              </div>
            </div>

            <div class="field">
              <label>所属系列</label>
              <input
                v-model="form.series"
                class="input"
                placeholder="可选，用于将同系列作品排在一起"
              />
            </div>
          </section>

          <section class="form-group">
            <h3 class="group-title">属性与分类</h3>
            <div class="field-grid three">
              <div class="field">
                <label>攻略进度</label>
                <select v-model="form.status" class="select">
                  <option value="todo">未开始</option>
                  <option value="playing">攻略中</option>
                  <option value="done">已通关</option>
                </select>
              </div>
              <div class="field">
                <label>平台角标</label>
                <select v-model="form.source_platform" class="select">
                  <option v-for="opt in PLATFORM_OPTIONS" :key="opt.label" :value="opt.value">
                    {{ opt.label }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>Bangumi 条目 ID</label>
                <input
                  v-model="form.bangumi_id"
                  class="input tabular-nums"
                  placeholder="可选，如 1195"
                />
              </div>
            </div>

            <!-- 气泡标签编辑器 (Tag Chips) -->
            <div class="field">
              <div class="label-row">
                <label>标签</label>
                <div class="field-tools">
                  <button
                    type="button"
                    class="field-search-btn"
                    title="在线查找并替换此项"
                    @click="openMetadataPicker('tags')"
                  >
                    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6">
                      <circle cx="7.2" cy="7.2" r="4.3" />
                      <path d="M10.5 10.5l2.8 2.8" stroke-linecap="round" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="lock-icon-btn"
                    :class="{ locked: isLocked('tags') }"
                    :title="lockTitle('tags')"
                    @click="toggleLock('tags')"
                  >
                    <svg v-if="isLocked('tags')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                    </svg>
                    <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                    </svg>
                  </button>
                </div>
              </div>
              <div class="tag-chips-editor" @click="focusTagInput">
                <span v-for="t in form.tags" :key="t" class="tag-chip-pill">
                  <span>{{ t }}</span>
                  <button type="button" class="tag-chip-del" :aria-label="`移除 ${t}`" @click.stop="removeTag(t)">
                    ×
                  </button>
                </span>
                <input
                  ref="tagInputRef"
                  v-model="tagDraft"
                  class="tag-inline-input"
                  :placeholder="form.tags.length === 0 ? '输入标签后按回车或逗号添加…' : '添加标签…'"
                  @keydown="handleTagKeydown"
                  @input="handleTagInput"
                  @blur="commitTagDraft"
                />
              </div>
            </div>

            <!-- 所属回廊分组 -->
            <div class="field">
              <div class="label-row">
                <label>所属回廊分组</label>
                <button type="button" class="subtle-link-btn" @click="store.openCreateCollectionModal()">
                  + 新建分组
                </button>
              </div>
              <div v-if="store.collections.length > 0" class="col-chips">
                <button
                  v-for="col in store.collections"
                  :key="col.id"
                  type="button"
                  class="col-chip"
                  :class="{ active: isInCollection(col.id) }"
                  @click="handleToggleCollection(col.id)"
                >
                  {{ col.name }}
                </button>
              </div>
              <div v-else class="col-empty-hint">暂无自定义分组</div>
            </div>
          </section>

          <section class="form-group">
            <div class="field">
              <div class="label-row">
                <label>剧情简介</label>
                <div class="field-tools">
                  <button
                    type="button"
                    class="field-search-btn"
                    title="在线查找并替换此项"
                    @click="openMetadataPicker('description')"
                  >
                    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6">
                      <circle cx="7.2" cy="7.2" r="4.3" />
                      <path d="M10.5 10.5l2.8 2.8" stroke-linecap="round" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    class="lock-icon-btn"
                    :class="{ locked: isLocked('synopsis') }"
                    :title="lockTitle('synopsis')"
                    @click="toggleLock('synopsis')"
                  >
                    <svg v-if="isLocked('synopsis')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                    </svg>
                    <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                    </svg>
                  </button>
                </div>
              </div>
              <textarea v-model="form.synopsis" class="textarea" rows="4" />
            </div>

            <label class="nsfw-check">
              <div>
                <div class="nsfw-title">成人向内容 (R18)</div>
                <div class="nsfw-desc">开启隐私模式后自动模糊此作品的封面、背景与截图</div>
              </div>
              <input v-model="form.is_nsfw" type="checkbox" class="native-switch" />
            </label>
          </section>
        </template>

        <!-- Tab 2: 视觉资产与原声 -->
        <template v-else-if="tab === 'media'">
          <section class="form-group">
            <h3 class="group-title">视觉资产</h3>
            <div class="asset-grid">
              <div v-for="card in assetCards" :key="card.key" class="asset-box">
                <div class="label-row">
                  <span class="asset-label">{{ card.label }}</span>
                  <div class="card-tools">
                    <button
                      v-if="card.preview"
                      type="button"
                      class="clear-icon-btn"
                      title="清除当前图片"
                      :disabled="clearingAsset === card.key"
                      @click="clearVisualAsset(card.key)"
                    >
                      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6">
                        <path d="M4 4l8 8M12 4L4 12" stroke-linecap="round" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      class="lock-icon-btn"
                      :class="{ locked: isLocked(card.key) }"
                      :title="lockTitle(card.key)"
                      @click="toggleLock(card.key)"
                    >
                      <svg v-if="isLocked(card.key)" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                      </svg>
                      <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                        <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                        <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                      </svg>
                    </button>
                  </div>
                </div>
                <div class="asset-preview">
                  <img v-if="card.preview" :src="card.preview" alt="" />
                  <span v-else class="asset-placeholder">暂无图片</span>
                </div>
                <div class="asset-action-row">
                  <label class="btn btn-sm asset-action-btn">
                    <span>{{ uploadingType === card.key ? '上传中…' : '本地上传' }}</span>
                    <input
                      type="file"
                      :accept="card.accept"
                      style="display: none"
                      @change="handleUpload(card.key, $event)"
                    />
                  </label>
                  <button
                    type="button"
                    class="btn btn-sm asset-action-btn"
                    @click="openAssetPicker(card.pickerKey)"
                  >
                    在线查找
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section class="form-group">
            <h3 class="group-title">宣传片与主题原声</h3>
            <div class="field">
              <div class="label-row">
                <div class="media-label-with-badge">
                  <label>官方宣传片 PV</label>
                  <span v-if="pvLocalActive" class="media-state-pill is-local">本地缓存</span>
                  <span v-else-if="pvRemoteUrl" class="media-state-pill is-remote">仅在线链接</span>
                  <span v-else class="media-state-pill">未配置</span>
                </div>
                <button
                  type="button"
                  class="lock-icon-btn"
                  :class="{ locked: isLocked('pv') }"
                  :title="lockTitle('pv')"
                  @click="toggleLock('pv')"
                >
                  <svg v-if="isLocked('pv')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                    <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                  </svg>
                  <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                    <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                  </svg>
                </button>
              </div>
              <div class="row-with-btn">
                <input
                  v-model="form.media.pv_url_or_path"
                  class="input"
                  placeholder="https://.../movie.mp4 / .m3u8 或上传本地视频"
                />
                <label class="btn btn-sm">
                  <span>{{ uploadingType === 'pv' ? '上传中…' : '上传视频' }}</span>
                  <input
                    type="file"
                    accept="video/*"
                    style="display: none"
                    @change="handleUpload('pv', $event)"
                  />
                </label>
                <button
                  type="button"
                  class="btn btn-sm"
                  @click="openAssetPicker('pv')"
                >
                  在线查找
                </button>
              </div>

              <!-- PV 模式互转快捷条 -->
              <div v-if="pvLocalActive || pvRemoteUrl" class="media-convert-bar">
                <span v-if="pvLocalActive && pvRemoteUrl" class="media-remote-caption" :title="pvRemoteUrl">
                  关联在线链接：{{ pvRemoteUrl }}
                </span>
                <span v-else-if="!pvLocalActive && pvRemoteUrl" class="media-remote-caption">
                  当前仅保留在线链接（节约磁盘空间）
                </span>
                <div class="media-convert-actions">
                  <button
                    v-if="!pvLocalActive && pvRemoteUrl"
                    type="button"
                    class="subtle-link-btn"
                    :disabled="mediaActionBusy"
                    @click="cacheRemoteMedia('pv')"
                  >
                    下载到本地
                  </button>
                  <button
                    v-if="pvLocalActive && pvRemoteUrl"
                    type="button"
                    class="subtle-link-btn"
                    :disabled="mediaActionBusy"
                    @click="dropLocalCacheMedia('pv')"
                  >
                    仅删除本地文件、保留在线链接
                  </button>
                  <button
                    v-if="pvLocalActive && !pvRemoteUrl"
                    type="button"
                    class="subtle-link-btn"
                    :disabled="mediaActionBusy"
                    @click="dropLocalCacheMedia('pv')"
                  >
                    删除本地文件
                  </button>
                </div>
              </div>

              <!-- PV 后台下载进度感知 -->
              <div
                v-if="pvTask && pvTask.status !== 'done'"
                class="pv-inline-task"
                :class="{ error: pvTask.status === 'error' }"
              >
                <div class="pv-inline-top">
                  <span>
                    <template v-if="pvTask.status === 'error'">
                      {{ pvTask.message || '本地视频下载失败，已保留在线链接可直接播放' }}
                    </template>
                    <template v-else>
                      正在缓存宣传片到本地
                      <span v-if="pvTask.progress != null" class="tabular-nums">{{ pvTask.progress }}%</span>
                    </template>
                  </span>
                  <div v-if="pvTask.status === 'error'" class="pv-inline-ops">
                    <button
                      v-if="taskStore.canRetryPv(game.id, pvRemoteUrl)"
                      type="button"
                      class="subtle-link-btn"
                      @click="taskStore.retryPvDownload(game.id, pvRemoteUrl)"
                    >
                      重试下载
                    </button>
                    <button
                      type="button"
                      class="subtle-link-btn"
                      @click="taskStore.keepLinkOnlyAndDismiss(game.id, 'pv', pvRemoteUrl)"
                    >
                      仅保留链接（忽略）
                    </button>
                  </div>
                </div>
                <div v-if="pvTask.status !== 'error'" class="pv-inline-track">
                  <div
                    class="pv-inline-fill"
                    :style="{ width: `${pvTask.progress ?? 12}%` }"
                  />
                </div>
              </div>
            </div>

            <!-- 主题原声 / OP 绑定与互转 -->
            <div class="field">
              <div class="label-row">
                <div class="media-label-with-badge">
                  <label>主题原声 / OP 音频（支持本地缓存与在线链接）</label>
                  <span v-if="bgmLocalActive" class="media-state-pill is-local">本地缓存</span>
                  <span v-else-if="bgmRemoteUrl" class="media-state-pill is-remote">仅在线链接</span>
                  <span v-else class="media-state-pill">未配置</span>
                </div>
                <button
                  type="button"
                  class="lock-icon-btn"
                  :class="{ locked: isLocked('bgm') }"
                  :title="lockTitle('bgm')"
                  @click="toggleLock('bgm')"
                >
                  <svg v-if="isLocked('bgm')" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                    <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                  </svg>
                  <svg v-else viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                    <path d="M5.5 7V5.2a2.5 2.5 0 0 1 4.6-1.3" stroke-linecap="round" />
                  </svg>
                </button>
              </div>
              <div class="row-with-btn">
                <input
                  v-model="form.media.bgm_path"
                  class="input"
                  placeholder="上传 .mp3 / .m4a / .flac / .ogg，或粘贴在线链接/本地路径"
                />
                <label class="btn btn-sm">
                  <span>{{ uploadingType === 'bgm' ? '上传中…' : '上传音频' }}</span>
                  <input
                    type="file"
                    accept=".mp3,.flac,.ogg,.wav,.m4a,.webm,audio/*"
                    style="display: none"
                    @change="handleUpload('bgm', $event)"
                  />
                </label>
                <button
                  v-if="form.media.bgm_path || bgmRemoteUrl"
                  type="button"
                  class="btn btn-sm btn-ghost"
                  @click="clearBgm"
                >
                  清除
                </button>
              </div>

              <!-- OP 模式互转快捷条 -->
              <div v-if="bgmLocalActive || bgmRemoteUrl" class="media-convert-bar">
                <span v-if="bgmLocalActive && bgmRemoteUrl" class="media-remote-caption" :title="bgmRemoteUrl">
                  关联在线链接：{{ bgmRemoteUrl }}
                </span>
                <span v-else-if="!bgmLocalActive && bgmRemoteUrl" class="media-remote-caption">
                  当前仅保留在线链接（节约磁盘空间）
                </span>
                <div class="media-convert-actions">
                  <button
                    v-if="!bgmLocalActive && bgmRemoteUrl"
                    type="button"
                    class="subtle-link-btn"
                    :disabled="mediaActionBusy"
                    @click="cacheRemoteMedia('bgm')"
                  >
                    下载到本地
                  </button>
                  <button
                    v-if="bgmLocalActive && bgmRemoteUrl"
                    type="button"
                    class="subtle-link-btn"
                    :disabled="mediaActionBusy"
                    @click="dropLocalCacheMedia('bgm')"
                  >
                    仅删除本地文件、保留在线链接
                  </button>
                </div>
              </div>

              <!-- OP 后台下载进度/错误感知 -->
              <div
                v-if="bgmTask && bgmTask.status !== 'done'"
                class="pv-inline-task"
                :class="{ error: bgmTask.status === 'error' }"
              >
                <div class="pv-inline-top">
                  <span>
                    <template v-if="bgmTask.status === 'error'">
                      {{ bgmTask.message || '本地音频下载失败，已保留在线链接可直接播放' }}
                    </template>
                    <template v-else>
                      正在缓存主题曲到本地
                      <span v-if="bgmTask.progress != null" class="tabular-nums">{{ bgmTask.progress }}%</span>
                    </template>
                  </span>
                  <div v-if="bgmTask.status === 'error'" class="pv-inline-ops">
                    <button
                      v-if="bgmRemoteUrl"
                      type="button"
                      class="subtle-link-btn"
                      @click="taskStore.retryBgmDownload(game.id)"
                    >
                      重试下载
                    </button>
                    <button
                      type="button"
                      class="subtle-link-btn"
                      @click="taskStore.keepLinkOnlyAndDismiss(game.id, 'bgm', bgmRemoteUrl)"
                    >
                      仅保留链接（忽略）
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 在线搜寻 OP 原声 -->
            <div class="music-finder">
              <div class="music-finder-head">
                <span class="music-finder-title">在线搜索主题曲</span>
                <div class="music-source-pills">
                  <button
                    v-for="src in MUSIC_SOURCES"
                    :key="src.key"
                    type="button"
                    class="music-src-pill"
                    :class="{ active: musicSource === src.key }"
                    :disabled="musicSearching"
                    @click="searchOnlineMusic(src.key)"
                  >
                    {{ src.label }}
                  </button>
                </div>
              </div>
              <div class="row-with-btn">
                <input
                  v-model="musicQuery"
                  class="input"
                  placeholder="输入日文原名或中文名搜索主题曲…"
                  @keydown.enter.prevent="searchOnlineMusic()"
                />
                <button
                  type="button"
                  class="btn btn-sm"
                  :disabled="musicSearching || !musicQuery.trim()"
                  @click="searchOnlineMusic()"
                >
                  {{ musicSearching ? '搜寻中…' : '搜寻 OP' }}
                </button>
              </div>

              <div v-if="musicCandidates.length > 0" class="music-list">
                <div v-for="item in musicCandidates" :key="item.id" class="music-row">
                  <div class="music-thumb">
                    <img v-if="item.thumbnail" :src="item.thumbnail" alt="" loading="lazy" />
                    <svg v-else viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6">
                      <path d="M8 14.5a2 2 0 1 1-2-2 2 2 0 0 1 2 2zm0 0V5l8-1.5v9.5m0 0a2 2 0 1 1-2-2 2 2 0 0 1 2 2z" />
                    </svg>
                  </div>
                  <div class="music-info">
                    <div class="music-title" :title="item.title">{{ item.title }}</div>
                    <div class="music-meta">
                      <span class="music-src">{{ item.source }}</span>
                      <span>{{ item.artist }}</span>
                      <span class="tabular-nums">{{ formatSec(item.duration) }}</span>
                    </div>
                  </div>
                  <div class="music-actions">
                    <button
                      type="button"
                      class="btn btn-sm btn-ghost"
                      @click="togglePreviewCandidate(item)"
                    >
                      {{ previewingId === item.id ? '停止' : '试听' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-ghost"
                      :disabled="Boolean(musicDownloadingId)"
                      @click="downloadCandidate(item, 'link_only')"
                    >
                      {{ musicDownloadingId === `${item.id}:link_only` ? '保存中…' : '仅保留链接' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm"
                      :disabled="Boolean(musicDownloadingId)"
                      @click="downloadCandidate(item, 'download')"
                    >
                      {{ musicDownloadingId === `${item.id}:download` ? '下载中…' : '下载到本地' }}
                    </button>
                  </div>
                </div>
              </div>

              <div v-else-if="musicSearchedOnce && !musicSearching" class="music-empty">
                未搜寻到可用原声候选，可尝试更换日文原名关键词或检查网络代理设置。
              </div>
            </div>
          </section>
        </template>

        <!-- Tab 3: 启动与目录 -->
        <template v-else>
          <section class="form-group">
            <h3 class="group-title">启动方案</h3>
            <div class="field">
              <label>启动方式</label>
              <select v-model="form.media.launch_mode" class="select">
                <option value="direct">直接运行本地 .exe / .lnk</option>
                <option value="le">通过 Locale Emulator 转区启动</option>
                <option value="cli">自定义命令行参数 / Steam URI</option>
              </select>
            </div>

            <div class="field">
              <label>主程序路径或协议 URI</label>
              <div class="row-with-btn">
                <input
                  v-model="form.media.exe_path"
                  class="input"
                  placeholder="例如 D:\Galgame\SummerPockets\SiglusEngine.exe 或 steam://rungameid/897220"
                />
                <button v-if="hasBridge" type="button" class="btn btn-sm" @click="pickPath('exe_path')">
                  选择…
                </button>
              </div>
            </div>

            <div class="field">
              <label>附加命令行参数（可选）</label>
              <input v-model="form.media.launch_args" class="input" placeholder="例如 -windowed --lang=zh" />
            </div>
          </section>

          <section class="form-group">
            <h3 class="group-title">本地关联目录</h3>
            <div class="field">
              <label>本地存档目录（用于快捷打开与 ZIP 快照备份）</label>
              <div class="row-with-btn">
                <input v-model="form.media.save_dir" class="input" placeholder="例如 D:\Galgame\SummerPockets\savedata" />
                <button v-if="hasBridge" type="button" class="btn btn-sm" @click="pickPath('save_dir')">
                  选择…
                </button>
              </div>
            </div>

            <div class="field">
              <label>本地截图 / CG 目录（留空则自动使用已下载的预览 CG）</label>
              <div class="row-with-btn">
                <input v-model="form.media.screenshot_dir" class="input" placeholder="例如 D:\Screenshots\SummerPockets" />
                <button v-if="hasBridge" type="button" class="btn btn-sm" @click="pickPath('screenshot_dir')">
                  选择…
                </button>
              </div>
            </div>
          </section>
        </template>
      </div>

      <div class="modal-foot edit-foot">
        <button type="button" class="btn btn-danger btn-sm" @click="removeGame">
          {{ confirmDelete ? '再次点击确认彻底删除' : '删除此游戏' }}
        </button>
        <div class="foot-right">
          <button type="button" class="btn btn-ghost" @click="store.showEditModal = false">取消</button>
          <button type="button" class="btn btn-primary" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存更改' }}
          </button>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <Transition name="modal-pop">
        <AssetPickerModal
          v-if="pickerAssetType && game"
          :game="game"
          :asset-type="pickerAssetType"
          @close="pickerAssetType = null"
          @applied="handleAssetApplied"
        />
      </Transition>
      <Transition name="modal-pop">
        <MetadataPickerModal
          v-if="showMetadataPicker && game"
          :current-form="form"
          :focus-field="metadataFocusField"
          @close="showMetadataPicker = false"
          @apply="handleMetadataApplied"
        />
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.edit-card {
  max-width: 780px;
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 20px 26px 14px;
}

.head-titles {
  min-width: 0;
}

.modal-head h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.modal-desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.close-icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.close-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

/* 精致底边指示条 Tab 栏 */
.edit-tabs {
  display: flex;
  gap: 22px;
  padding: 0 26px;
  border-bottom: 1px solid var(--divider-subtle);
}

.edit-tabs button {
  position: relative;
  padding: 10px 2px 12px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 500;
  transition: color var(--duration-fast) var(--ease-out-expo);
}

.edit-tabs button::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  border-radius: 2px;
  background: #f5f5f7;
  opacity: 0;
  transform: scaleX(0.4);
  transition:
    opacity var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo);
}

.edit-tabs button:hover {
  color: var(--text-secondary);
}

.edit-tabs button.active {
  color: var(--text-primary);
}

.edit-tabs button.active::after {
  opacity: 1;
  transform: scaleX(1);
}

.modal-body {
  padding: 22px 26px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.group-title {
  margin: 0;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.group-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.meta-replace-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: none;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.meta-replace-btn:hover {
  background: rgba(255, 255, 255, 0.11);
  color: var(--text-primary);
}

.field-tools {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.field-search-btn {
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  opacity: 0.42;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    opacity var(--duration-fast) var(--ease-out-expo),
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.field-search-btn:hover {
  opacity: 1;
  background: var(--surface-hover);
  color: var(--text-primary);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-secondary);
}

.edit-card :deep(.input),
.edit-card :deep(.select),
.edit-card :deep(.textarea) {
  font-size: 14px;
  font-weight: 400;
  color: #f4f4f5;
}

.label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

/* 极简锁图标按钮 */
.lock-icon-btn {
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  opacity: 0.42;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    opacity var(--duration-fast) var(--ease-out-expo),
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.lock-icon-btn:hover {
  opacity: 1;
  background: var(--surface-hover);
  color: var(--text-primary);
}

.lock-icon-btn.locked {
  opacity: 1;
  color: var(--amber-text);
  background: var(--amber-bg);
}

.subtle-link-btn {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.subtle-link-btn:hover {
  color: var(--text-primary);
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.field-grid.three {
  grid-template-columns: repeat(3, 1fr);
}

.row-with-btn {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* Tag Chips 气泡标签编辑器 */
.tag-chips-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 40px;
  padding: 6px 10px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.07);
  cursor: text;
  transition:
    border-color var(--duration-fast) var(--ease-out-expo),
    background-color var(--duration-fast) var(--ease-out-expo);
}

.tag-chips-editor:focus-within {
  background: rgba(255, 255, 255, 0.065);
  border-color: var(--border-focus);
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.05);
}

.tag-chip-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.09);
  font-size: 12.5px;
  font-weight: 400;
  color: var(--text-primary);
}

.tag-chip-del {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1;
}

.tag-chip-del:hover {
  color: #ffffff;
}

.tag-inline-input {
  flex: 1;
  min-width: 120px;
  border: none;
  background: transparent;
  outline: none;
  font-size: 13.5px;
  font-weight: 400;
  color: var(--text-primary);
  padding: 2px 0;
}

.tag-inline-input::placeholder {
  color: var(--text-muted);
}

.col-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.col-chip {
  padding: 5px 11px;
  border: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary);
  font-size: 12px;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.col-chip:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.col-chip.active {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 500;
}

.col-empty-hint {
  font-size: 12px;
  color: var(--text-muted);
}

.nsfw-check {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
}

.nsfw-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.nsfw-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* Assets */
.asset-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.asset-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.028);
}

.asset-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.card-tools {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.clear-icon-btn {
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  opacity: 0.36;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    opacity var(--duration-fast) var(--ease-out-expo),
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.clear-icon-btn:hover:not(:disabled) {
  opacity: 1;
  background: var(--surface-hover);
  color: var(--danger-text);
}

.asset-preview {
  height: 118px;
  border-radius: 8px;
  overflow: hidden;
  background: repeating-conic-gradient(rgba(255, 255, 255, 0.035) 0% 25%, transparent 0% 50%) 50% / 16px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.asset-preview img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.asset-placeholder {
  font-size: 12px;
  color: var(--text-muted);
}

.asset-action-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.asset-action-btn {
  width: 100%;
}

.media-label-with-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.media-state-pill {
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-muted);
}

.media-state-pill.is-local {
  background: rgba(52, 211, 153, 0.14);
  color: #6ee7b7;
}

.media-state-pill.is-remote {
  background: rgba(96, 165, 250, 0.14);
  color: #93c5fd;
}

.media-convert-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 4px;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.025);
}

.media-remote-caption {
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 300px;
}

.media-convert-actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

/* 在线搜寻 OP 原声 */
.music-finder {
  margin-top: 4px;
  padding: 14px 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.028);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.music-finder-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.music-finder-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.music-finder-sub {
  font-size: 11.5px;
  color: var(--text-muted);
}

.music-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 220px;
  overflow-y: auto;
}

.music-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.025);
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.music-row:hover {
  background: rgba(255, 255, 255, 0.06);
}

.music-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  flex-shrink: 0;
}

.music-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.music-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.music-title {
  font-size: 13px;
  font-weight: 400;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.music-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.music-src {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}

.music-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.music-empty {
  text-align: center;
  padding: 14px 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.edit-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 26px;
  border-top: 1px solid var(--divider-subtle);
}

.pv-inline-task {
  margin-top: 6px;
  padding: 8px 11px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.035);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pv-inline-task.error {
  background: rgba(248, 113, 113, 0.08);
  color: var(--danger-text);
}

.pv-inline-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  color: var(--text-secondary);
}

.pv-inline-task.error .pv-inline-top {
  color: var(--danger-text);
}

.pv-inline-ops {
  display: inline-flex;
  gap: 10px;
}

.pv-inline-track {
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.pv-inline-fill {
  height: 100%;
  border-radius: 999px;
  background: #f5f5f7;
  transition: width 240ms var(--ease-out-expo);
}

.foot-right {
  display: flex;
  gap: 10px;
}

.music-source-pills {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.04);
}

.music-src-pill {
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  font-size: 11px;
  padding: 2px 7px;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.music-src-pill:hover:not(:disabled) {
  color: var(--text-primary);
}

.music-src-pill.active {
  background: rgba(255, 255, 255, 0.14);
  color: #f5f5f7;
  font-weight: 500;
}
</style>
