import { test } from 'playwright/test';

const BASE = 'http://127.0.0.1:3005';

async function sendPrompt(page, mode, prompt) {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);

  await page.locator('label:has-text("模式")').locator('xpath=..').locator('select').selectOption(mode);

  const box = page.locator('textarea.composer-input');
  await box.fill(prompt);
  await page.locator('button.send-btn').click();

  await page.waitForTimeout(4500);
}

test('wind_agent should render analysis result', async ({ page }) => {
  const prompt = '请分析风况并输出分析图，输入文件是 C:/wind-agent/wind_data/wind condition @Akida.xlsx';
  await sendPrompt(page, 'wind_agent', prompt);
  await page.screenshot({ path: 'C:/wind-agent/tmp/e2e/wind_agent.png', fullPage: true });
});

test('typhoon_model should render map feedback', async ({ page }) => {
  const prompt = '请给出台风概率并展示地图，lat=20.9339, lon=112.202, radius_km=100, model_scope=scs';
  await sendPrompt(page, 'typhoon_model', prompt);
  await page.waitForSelector('#map .leaflet-pane, #map .leaflet-control-zoom', { timeout: 15000 });
  await page.screenshot({ path: 'C:/wind-agent/tmp/e2e/typhoon_model.png', fullPage: true });
});
