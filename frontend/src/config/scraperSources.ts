export type ScraperAuthType = 'none' | 'optional' | 'required'

export interface ScraperSourceConfig {
  id: string
  name: string
  description: string
  authType: ScraperAuthType
  keyField?: string
  placeholder?: string
  docHint?: string
}

/**
 * 可扩展数据源注册表
 * 新增数据源时，直接追加一条配置对象即可自动在设置页渲染。
 */
export const SCRAPER_SOURCES: ScraperSourceConfig[] = [
  {
    id: 'vndb',
    name: 'VNDB',
    description: '原名、开发商与类型标签',
    authType: 'none',
  },
  {
    id: 'steam',
    name: 'Steam',
    description: '商店简介、宣传片与截图',
    authType: 'none',
  },
  {
    id: 'steamgriddb',
    name: 'SteamGridDB',
    description: '透明 Logo 与宽幅背景',
    authType: 'required',
    keyField: 'steamgriddb',
    placeholder: '输入 SteamGridDB API Key',
    docHint: '登录 steamgriddb.com，在 Preferences → API 页面获取。',
  },
  {
    id: 'bangumi',
    name: 'Bangumi',
    description: '中文标题、简介与发售日',
    authType: 'optional',
    keyField: 'bangumi',
    placeholder: '可选，留空可正常搜索公开条目',
    docHint: '可在 next.bgm.tv/demo/access-token 生成个人令牌。',
  },
  {
    id: 'touchgal',
    name: 'TouchGal',
    description: '中文译名与社区资料补充',
    authType: 'optional',
    keyField: 'touchgal',
    placeholder: '可选，填写社区 Token',
    docHint: '拥有 TouchGal Token 时可在此填入。',
  },
]
