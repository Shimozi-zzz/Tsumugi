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
  // ── 1. 免 Key 开箱即用源（默认全部启用） ──
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
        placeholder: '留空使用官方公开只读通道',
      },
      {
        key: 'ymgal_client_secret',
        label: 'Client Secret（可选）',
        placeholder: '填入专属 Client Secret 提升配额',
        isSecret: true,
      },
    ],
    docUrl: 'https://www.ymgal.games/developer',
    docLinkLabel: '开放平台文档 ↗',
    docHint: '无需配置即可开箱使用公开只读检索；如持有月幕开发者凭证可在此填写。',
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
    docHint: '默认使用官方域名 kungal.com，可配置自定义镜像地址或可选访问 Token。',
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
    docHint: '免 Key 开箱即用，在导入搜索框直接粘贴 RJ123456 编号即可精准命中。',
  },
  {
    id: 'vndb',
    name: 'VNDB',
    shortName: 'VNDB',
    description: '视觉小说百科 API v2，支持 v{id} 直查、别名与 Steam / DLsite 关联',
    group: 'free',
    authType: 'none',
    docUrl: 'https://vndb.org',
    docLinkLabel: '访问 VNDB ↗',
    docHint: '免 Key 免费使用，自动提取日文原名、开发商、防剧透标签与外链 ID。',
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
        placeholder: '留空可正常搜索；填写后提升限额并支持同步游玩状态',
        isSecret: true,
      },
    ],
    docUrl: 'https://next.bgm.tv/demo/access-token',
    docLinkLabel: '获取 Token ↗',
    docHint: '在 next.bgm.tv/demo/access-token 生成个人令牌，可提升请求配额并开启状态同步。',
  },
  {
    id: 'steam',
    name: 'Steam Store',
    shortName: 'Steam',
    description: '中文商店元数据、官方 PV 预告片及商店链接 / 纯数字 AppID 直查',
    group: 'free',
    authType: 'none',
    docUrl: 'https://store.steampowered.com',
    docLinkLabel: '访问 Steam ↗',
    docHint: '免 Key 开箱即用，直接粘贴商店链接或数字 AppID 可 100% 精准命中。',
  },

  // ── 2. 可选 API Key 扩展源（填 Key 自动解锁） ──
  {
    id: 'touchgal',
    name: 'TouchGal',
    shortName: 'TouchGal',
    description: '中文 Galgame 社区资料库，专精中文译名、汉化简介与宽幅横版封面',
    group: 'key',
    authType: 'required',
    fields: [
      {
        key: 'touchgal_api_key',
        label: 'API Key',
        placeholder: '输入 TouchGal 第三方 API Key',
        isSecret: true,
      },
    ],
    docUrl: 'https://www.touchgal.io',
    docLinkLabel: '访问 TouchGal ↗',
    docHint: '填写第三方 API Key 后将自动加入「综合推荐」聚合搜索，并支持 touchgal.io 链接直查。',
  },
  {
    id: 'steamgriddb',
    name: 'SteamGridDB',
    shortName: 'SteamGridDB',
    description: '高清竖版展架封面（Grid 600×900）、宽屏背景（Hero）与透明 Logo',
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
    docHint: '登录 steamgriddb.com → Preferences → API 页面免费生成，填入后自动解锁高清换封面。',
  },
  {
    id: 'igdb',
    name: 'IGDB',
    shortName: 'IGDB',
    description: '补足主机独占与非 Steam 综合单机元数据（Twitch OAuth 鉴权）',
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
    docHint: '在 Twitch Developer Console 注册应用获取 Client ID 与 Secret，填入后在综合单机搜索中自动解锁。',
  },
]

export const FREE_SCRAPER_SOURCES = SCRAPER_SOURCES.filter((s) => s.group === 'free')
export const KEY_SCRAPER_SOURCES = SCRAPER_SOURCES.filter((s) => s.group === 'key')
