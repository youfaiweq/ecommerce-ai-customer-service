/**
 * 精简 Markdown 渲染（零依赖）。
 *
 * 后端回复是 Markdown，但门店前端没有引入 marked。为避免增加打包体积与第三方依赖，
 * 这里实现一个覆盖常见语法（标题/列表/加粗/行内代码/链接/换行）的小渲染器。
 *
 * 安全：先对整段文本做 HTML 转义，再在“已转义文本”上做标记替换，
 * 因此用户/模型内容里的原始标签不会产生可执行 HTML（防 XSS）。
 * 链接仅允许 http/https 协议。
 */

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInline(escaped: string): string {
  let s = escaped
  // 行内代码 `code`
  s = s.replace(/`([^`]+)`/g, (_m, code: string) => `<code>${code}</code>`)
  // 加粗 **text**
  s = s.replace(/\*\*([^*]+)\*\*/g, (_m, t: string) => `<strong>${t}</strong>`)
  // 链接 [text](https://...)，协议白名单（此时 & 已转义为 &amp;）
  s = s.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_m, text: string, url: string) =>
      `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`,
  )
  return s
}

export function renderMarkdown(text: string): string {
  const escaped = escapeHtml(text ?? '')
  const lines = escaped.split(/\r?\n/)
  const html: string[] = []
  let listOpen = false

  const closeList = () => {
    if (listOpen) {
      html.push('</ul>')
      listOpen = false
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) {
      closeList()
      continue
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    const bullet = line.match(/^[-*]\s+(.*)$/)
    const ordered = line.match(/^\d+[.)]\s+(.*)$/)
    if (heading) {
      closeList()
      const level = heading[1].length
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`)
    } else if (bullet || ordered) {
      if (!listOpen) {
        html.push('<ul>')
        listOpen = true
      }
      html.push(`<li>${renderInline((bullet || ordered)![1])}</li>`)
    } else {
      closeList()
      html.push(`<p>${renderInline(line)}</p>`)
    }
  }
  closeList()
  return html.join('')
}
