export type ScraperAuthType = 'none' | 'optional' | 'required'
export type ScraperGroup = 'free' | 'key'

export interface ScraperFieldConfig {
  key:
    | 'ymgal_client_id'
    | 'ymgal_client_secret'
    | 'kungal_base_url'
    | 'kungal_token'
    | 'bangumi_token'
    | 'touchgal_api_key'
    | 'steamgriddb_api_key'
    | 'igdb_client_id'
    | 'igdb_client_secret'
  label: string
  placeholder: string
  isSecret?: boolean
  defaultValue?: string
}

export interface ScraperSourceConfig {
  id: 'ymgal' | 'kungal' | 'dlsite' | 'vndb' | 'bangumi' | 'steam' | 'touchgal' | 'steamgriddb' | 'igdb'
  name: string
  shortName: string
  description: string
  group: ScraperGroup
  authType: ScraperAuthType
  fields?: ScraperFieldConfig[]
  docUrl?: string
  docLinkLabel?: string
  docHint?: string
}

/**
 * 统一元数据刮削源配置目录（用于设置页「元数据刮削源」分组渲染）
 */
export const SCRAPER_SOURCES: ScraperSourceConfig[] = [
  // ── 1. 内置数据源（免 Key） ──
  {
    id: 'ymgal',
    name: 'YMGal 月幕 Galgame',
    shortName: 'YMGal',
    description: '中文 Galgame 档案库，支持 GA 编号直查与 OAuth / 公开只读检索',
    group: 'free',
    authType: 'optional',
    fields: [
      {
        key: 'ymgal_client_id',
        label: 'Client ID（可选）',
        placeholder: '留空使用公开只读接口',
      },
      {
        key: 'ymgal_client_secret',
        label: 'Client Secret（可选）',
        placeholder: '填写 Client Secret 提升配额',
        isSecret: true,
      },
    ],
    docUrl: 'https://www.ymgal.games/developer',
    docLinkLabel: '开放平台文档 ↗',
    docHint: '默认使用公开只读接口，填写开发者凭证可提高配额。',
  },
  {
    id: 'kungal',
    name: 'Kungal 鲲Gal',
    shortName: 'Kungal',
    description: '中文视觉小说社区资料库，支持 kungal.com/galgame/{id} 直查',
    group: 'free',
    authType: 'optional',
    fields: [
      {
        key: 'kungal_base_url',
        label: 'API Base URL',
        placeholder: 'https://www.kungal.com',
        defaultValue: 'https://www.kungal.com',
      },
      {
        key: 'kungal_token',
        label: '请求 Token（可选）',
        placeholder: '可选，用于认证或自定义节点',
        isSecret: true,
      },
    ],
    docUrl: 'https://www.kungal.com',
    docLinkLabel: '访问鲲Gal ↗',
    docHint: '默认使用 kungal.com，可配置自定义地址或访问 Token。',
  },
  {
    id: 'dlsite',
    name: 'DLsite',
    shortName: 'DLsite',
    description: '同人 / 独立视觉小说，支持 RJ / VJ / BJ 作品编号与商品链接直查',
    group: 'free',
    authType: 'none',
    docUrl: 'https://www.dlsite.com',
    docLinkLabel: '访问 DLsite ↗',
    docHint: '免 Key，支持粘贴 RJ 编号或商品链接查询。',
  },
  {
    id: 'vndb',
    name: 'VNDB',
    shortName: 'VNDB',
    description: '视觉小说数据库 API v2，支持 v{id} 直查、别名与 Steam / DLsite 关联',
    group: 'free',
    authType: 'none',
    docUrl: 'https://vndb.org',
    docLinkLabel: '访问 VNDB ↗',
    docHint: '免 Key，支持提取原名、开发商、标签与外链 ID。',
  },
  {
    id: 'bangumi',
    name: 'Bangumi 番组计划',
    shortName: 'Bangumi',
    description: '中文游戏条目、别名、简介与评分（支持 bgm.tv/subject/{id} 直查）',
    group: 'free',
    authType: 'optional',
    fields: [
      {
        key: 'bangumi_token',
        label: 'Access Token（可选）',
        placeholder: '留空可搜索，填写后提升限额并支持同步状态',
        isSecret: true,
      },
    ],
    docUrl: 'https://next.bgm.tv/demo/access-token',
    docLinkLabel: '获取 Token ↗',
    docHint: '在 next.bgm.tv/demo/access-token 生成个人令牌，可提升配额并同步游玩状态。',
  },
  {
    id: 'steam',
    name: 'Steam Store',
    shortName: 'Steam',
    description: '中文商店元数据、官方 PV 预告片及商店链接 / 数字 AppID 直查',
    group: 'free',
    authType: 'none',
    docUrl: 'https://store.steampowered.com',
    docLinkLabel: '访问 Steam ↗',
    docHint: '免 Key，支持粘贴商店链接或数字 AppID 查询。',
  },

  // ── 2. 可选扩展源（填写 Key 后可用） ──
  {
    id: 'touchgal',
    name: 'TouchGal',
    shortName: 'TouchGal',
    description: '中文译名、简介与横版封面',
    group: 'key',
    authType: 'required',
    fields: [
      {
        key: 'touchgal_api_key',
        label: 'API Key',
        placeholder: '输入 tgal_live_<id>-<secret> 格式 API Key',
        isSecret: true,
      },
    ],
    docUrl: 'https://developer.touchgal.com',
    docLinkLabel: '开发者平台 ↗',
    docHint: '填写 TouchGal 开发者 API Key（tgal_live_<id>-<secret>）后启用。',
  },
  {
    id: 'steamgriddb',
    name: 'SteamGridDB',
    shortName: 'SteamGridDB',
    description: '竖版封面、宽幅背景（Hero）与透明 Logo',
    group: 'key',
    authType: 'required',
    fields: [
      {
        key: 'steamgriddb_api_key',
        label: 'API Key',
        placeholder: '输入 SteamGridDB API Key',
        isSecret: true,
      },
    ],
    docUrl: 'https://www.steamgriddb.com/profile/preferences/api',
    docLinkLabel: '获取 API Key ↗',
    docHint: '在 steamgriddb.com 的 Preferences / API 页面生成 Key，填写后可用于封面与背景查找。',
  },
  {
    id: 'igdb',
    name: 'IGDB',
    shortName: 'IGDB',
    description: '主机独占与非 Steam 单机元数据（Twitch OAuth 鉴权）',
    group: 'key',
    authType: 'required',
    fields: [
      {
        key: 'igdb_client_id',
        label: 'Twitch Client ID',
        placeholder: '输入 Twitch 应用 Client ID',
      },
      {
        key: 'igdb_client_secret',
        label: 'Twitch Client Secret',
        placeholder: '输入 Twitch 应用 Client Secret',
        isSecret: true,
      },
    ],
    docUrl: 'https://dev.twitch.tv/console/apps',
    docLinkLabel: 'Twitch 开发者控制台 ↗',
    docHint: '在 Twitch 开发者控制台获取 Client ID 与 Secret，填写后启用。',
  },
]

export const FREE_SCRAPER_SOURCES = SCRAPER_SOURCES.filter((s) => s.group === 'free')
export const KEY_SCRAPER_SOURCES = SCRAPER_SOURCES.filter((s) => s.group === 'key')
