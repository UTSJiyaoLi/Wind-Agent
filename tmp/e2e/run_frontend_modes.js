const { chromium } = require('playwright');

const BASE = 'http://127.0.0.1:3005';

async function run(mode, prompt, outFile, waitForMap = false) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1700, height: 980 } });
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);

  const modeSelect = page.locator('label:has-text("模式")').locator('xpath=..').locator('select');
  await modeSelect.selectOption(mode);

  const box = page.locator('textarea.composer-input');
  await box.fill(prompt);
  await page.locator('button.send-btn').click();

  await page.waitForTimeout(7000);
  if (waitForMap) {
    await page.waitForSelector('#map .leaflet-pane, #map .leaflet-control-zoom', { timeout: 20000 });
  }

  await page.screenshot({ path: outFile, fullPage: true });

  const hasMap = (await page.locator('#map .leaflet-pane, #map .leaflet-control-zoom').count()) > 0;
  const hasImg = (await page.locator('.gallery img, .markdown-body img, img').count()) > 0;
  const streamText = (await page.locator('.msg-card.streaming').first().innerText().catch(()=>'')) || '';
  const runtimeText = (await page.locator('.settings-block .mono.slim').first().innerText().catch(()=>'')) || '';

  await browser.close();
  return { mode, hasMap, hasImg, streamPreview: streamText.slice(0, 220), runtimeText };
}

(async () => {
  const results = [];
  results.push(await run(
    'wind_agent',
    '请分析风况并输出分析图，输入文件是 C:/wind-agent/wind_data/wind condition @Akida.xlsx',
    'C:/wind-agent/tmp/e2e/wind_agent.png',
    false
  ));
  results.push(await run(
    'typhoon_model',
    '请给出台风概率并展示地图，lat=20.9339, lon=112.202, radius_km=100, model_scope=scs',
    'C:/wind-agent/tmp/e2e/typhoon_model.png',
    true
  ));
  console.log(JSON.stringify(results, null, 2));
})();
