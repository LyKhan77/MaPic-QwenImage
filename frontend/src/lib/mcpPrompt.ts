export type McpToolPreset = 'all' | 'generate' | 'remove-background'

export function resolveMcpEndpointUrl(apiUrl?: string, hostname?: string): string {
  const raw = (apiUrl || '').trim().replace(/\/+$/, '')
  if (raw) {
    const base = raw.endsWith('/api') ? raw.slice(0, -4) : raw
    return `${base}/mcp`
  }
  const host = (hostname || '').trim() || 'localhost'
  return `http://${host}:8281/mcp`
}

export function buildMcpConfigJson(endpointUrl: string, token?: string): string {
  const resolvedToken = (token || '').trim() || '<MAPIC_SERVICE_TOKEN>'
  const resolvedUrl = endpointUrl.trim() || 'http://localhost:8281/mcp'
  return JSON.stringify(
    {
      mcpServers: {
        mapic: {
          url: resolvedUrl,
          headers: {
            Authorization: `Bearer ${resolvedToken}`,
          },
        },
      },
    },
    null,
    2,
  )
}

export function buildAgentMcpPrompt(options: {
  endpointUrl: string
  token?: string
  preset: McpToolPreset
}): string {
  const configJson = buildMcpConfigJson(options.endpointUrl, options.token)
  const sections: string[] = [
    'Connect the MaPic MCP server (Streamable HTTP) to my workspace/agent configuration using the server config below:',
    '',
    '```json',
    configJson,
    '```',
    '',
    'Available tool guidelines:',
  ]

  if (options.preset === 'all' || options.preset === 'generate') {
    sections.push(
      '- `generate_image`: Use for text-to-image (`prompt`) or image-to-image editing (`prompt` + `images`, up to 10 base64 PNG/JPEG strings without data-URL prefix, <= 2 MiB each). Default `resolution` is `1024`, `num_inference_steps` is `40` (range 20-75). Put exact rendered text inside quotes.',
    )
  }

  if (options.preset === 'all' || options.preset === 'remove-background') {
    sections.push(
      '- `remove_background`: Use for fast CPU background removal (`image`: one base64 PNG/JPEG string without data-URL prefix, <= 2 MiB and <= 2048 px). Returns a transparent RGBA PNG without waiting in the GPU queue.',
    )
  }

  sections.push(
    '- `get_model_status`: Use to verify readiness, active GPU node, and free VRAM before running generation.',
    '',
    'After configuring the MCP server, verify the connection by listing tools or calling `get_model_status`, and report which MaPic tools are ready.',
  )

  return sections.join('\n')
}
