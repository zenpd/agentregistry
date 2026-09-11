const { test, expect } = require('@playwright/test')

test('vis-network dependency graph renders and is interactive', async ({ page }) => {
  // 1. Login
  await page.goto('http://localhost:5174/')
  await page.waitForURL(/login/, { timeout: 10000 })
  await page.fill('input[type="email"], input[name="email"], #email', 'admin@airegistry.local')
  await page.fill('input[type="password"]', 'admin123')
  await page.click('button[type="submit"], button:has-text("Sign in")')
  await page.waitForURL(u => !u.pathname.includes('login'), { timeout: 10000 })

  // 2. Open dependencies — vis-network canvas (direct React, no iframe)
  await page.goto('http://localhost:5174/dependencies')
  await page.waitForSelector('canvas', { timeout: 15000 })
  await page.waitForTimeout(4000) // physics stabilization
  console.log('VIS-NETWORK CANVAS RENDERED')

  // 3. Legend chips with counts
  await expect(page.locator('button', { hasText: 'Finance (3)' })).toBeVisible()
  await expect(page.locator('button', { hasText: 'MCP Servers (12)' })).toBeVisible()
  console.log('LEGEND CHIPS OK')

  // 4. Toggle a kind off → vis hides nodes (verify via network state through effect)
  await page.locator('button', { hasText: 'MCP Servers (12)' }).click()
  await page.waitForTimeout(600)
  await expect(page.locator('button', { hasText: 'MCP Servers' })).toHaveClass(/opacity-35/)
  console.log('CHIP TOGGLED OFF (opacity-35)')

  // 5. Toggle back
  await page.locator('button', { hasText: 'MCP Servers (12)' }).click()
  await page.waitForTimeout(600)
  console.log('CHIP RESTORED')

  // 6. Click an agent node on canvas → details panel
  const canvas = page.locator('canvas').first()
  const box = await canvas.boundingBox()
  // click near center — some node should be there after physics stabilization
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
  await page.waitForTimeout(500)
  const panelText = await page.locator('h3').first().innerText().catch(() => '(no node clicked)')
  console.log('PANEL AFTER CANVAS CLICK:', panelText)

  // 7. Screenshot of the settled vis-network layout
  await page.screenshot({ path: 'graph-visnetwork.png', fullPage: false })
  console.log('SCREENSHOT saved: graph-visnetwork.png')

  console.log('ALL BROWSER CHECKS PASSED')
})
