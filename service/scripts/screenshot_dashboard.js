// Screenshot the provisioned Grafana dashboard (compose stack must be up).
// Usage: node scripts/screenshot_dashboard.js [out.png] [grafana base URL]
// Needs the playwright package and its Chromium (NODE_PATH may point at a global install).
const { chromium } = require('playwright');

(async () => {
  const out = process.argv[2] || 'docs/grafana-dashboard.png';
  const base = process.argv[3] || 'http://127.0.0.1:3000';
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1250 } });
  await page.goto(`${base}/d/ppe-service/ppe-service?orgId=1&from=now-6m&to=now&kiosk`, {
    waitUntil: 'networkidle',
  });
  await page.waitForSelector('[data-testid="data-testid panel content"], .panel-content', {
    timeout: 30000,
  }).catch(() => {});
  await page.waitForTimeout(6000);
  await page.screenshot({ path: out, fullPage: true });
  await browser.close();
  console.log(`saved ${out}`);
})();
