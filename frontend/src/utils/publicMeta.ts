export interface PublicPageMeta {
  title: string
  description: string
  type?: 'website' | 'article'
  url?: string
}

function upsertMeta(attribute: 'name' | 'property', key: string, content: string): void {
  let element = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${key}"]`)
  if (!element) {
    element = document.createElement('meta')
    element.setAttribute(attribute, key)
    document.head.appendChild(element)
  }
  element.content = content
}

/** Update the static, client-rendered metadata for the public routes. */
export function setPublicPageMeta(meta: PublicPageMeta): void {
  if (typeof document === 'undefined') return

  document.title = meta.title
  upsertMeta('name', 'description', meta.description)
  upsertMeta('property', 'og:title', meta.title)
  upsertMeta('property', 'og:description', meta.description)
  upsertMeta('property', 'og:type', meta.type || 'website')
  upsertMeta('property', 'og:url', meta.url || window.location.href)
  upsertMeta('name', 'twitter:card', 'summary')
  upsertMeta('name', 'twitter:title', meta.title)
  upsertMeta('name', 'twitter:description', meta.description)
}
