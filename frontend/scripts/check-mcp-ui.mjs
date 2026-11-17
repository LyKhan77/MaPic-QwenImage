import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { buildAgentMcpPrompt, buildMcpConfigJson, resolveMcpEndpointUrl } from '../src/lib/mcpPrompt.ts'

assert.equal(resolveMcpEndpointUrl('http://192.168.2.133:8281/api'), 'http://192.168.2.133:8281/mcp')
assert.equal(resolveMcpEndpointUrl('http://192.168.2.133:8281/api/'), 'http://192.168.2.133:8281/mcp')
assert.equal(resolveMcpEndpointUrl(undefined, '192.168.2.133'), 'http://192.168.2.133:8281/mcp')

const defaultConfig = JSON.parse(buildMcpConfigJson('http://192.168.2.133:8281/mcp'))
assert.equal(defaultConfig.mcpServers.mapic.url, 'http://192.168.2.133:8281/mcp')
assert.equal(defaultConfig.mcpServers.mapic.headers.Authorization, 'Bearer <MAPIC_SERVICE_TOKEN>')

const tokenConfig = JSON.parse(buildMcpConfigJson('http://192.168.2.133:8281/mcp', 'abc-123'))
assert.equal(tokenConfig.mcpServers.mapic.headers.Authorization, 'Bearer abc-123')

const allPrompt = buildAgentMcpPrompt({ endpointUrl: 'http://192.168.2.133:8281/mcp', preset: 'all' })
assert.ok(allPrompt.includes('`generate_image`'))
assert.ok(allPrompt.includes('`remove_background`'))
assert.ok(allPrompt.includes('`get_model_status`'))

const genOnly = buildAgentMcpPrompt({ endpointUrl: 'http://192.168.2.133:8281/mcp', preset: 'generate' })
assert.ok(genOnly.includes('`generate_image`'))
assert.ok(!genOnly.includes('`remove_background`'))

const bgOnly = buildAgentMcpPrompt({ endpointUrl: 'http://192.168.2.133:8281/mcp', preset: 'remove-background' })
assert.ok(bgOnly.includes('`remove_background`'))
assert.ok(!bgOnly.includes('`generate_image`'))

const sidebar = readFileSync(new URL('../src/components/Sidebar.tsx', import.meta.url), 'utf8')
const login = readFileSync(new URL('../src/pages/Login.tsx', import.meta.url), 'utf8')
assert.ok(sidebar.includes('ConnectMcpModal'), 'Sidebar must mount ConnectMcpModal')
assert.ok(login.includes('ConnectMcpModal'), 'Login page must mount ConnectMcpModal')

console.log('mcpPrompt: endpoint URL, config JSON, presets, and Sidebar/Login wiring OK')
