// Records the Transakt demo page clicking through all six steps against the LIVE API,
// then writes tools/out/transakt-demo.webm and two screenshots. Run by .github/workflows/record-demos.yml.
const { chromium } = require('playwright');
(async () => {
  const out = 'tools/out/';
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 960, height: 760 }, colorScheme: 'light',
    recordVideo: { dir: out + 'video', size: { width: 960, height: 760 } } });
  const p = await ctx.newPage();
  await p.goto('https://arv0007.github.io/demos/transakt/', { waitUntil: 'networkidle' });
  await p.waitForTimeout(1200);
  const steps = ['wake', 'signup', 'pay', 'retry', 'ledger', 'forge'];
  for (const s of steps) {
    const btn = p.locator(`button[data-run=${s}]`);
    await btn.scrollIntoViewIfNeeded();
    await p.waitForTimeout(500);
    for (let attempt = 0; attempt < 4; attempt++) {
      await btn.click();
      await p.waitForFunction(r => document.querySelector(`button[data-run=${r}]`).textContent !== 'Sending…', s, { timeout: 150000 });
      const done = await p.evaluate(r => document.querySelector(`button[data-run=${r}]`).closest('.step').classList.contains('done'), s);
      if (done) break;
      await p.waitForTimeout(8000);   // server still waking up: try again
    }
    const verdict = await p.evaluate(r => (document.querySelector(`button[data-run=${r}]`).closest('.step').querySelector('.verdict') || {}).textContent, s);
    console.log(s, '|', verdict);
    const res = p.locator(`button[data-run=${s}]`).locator('xpath=ancestor::li').locator('.result');
    await res.scrollIntoViewIfNeeded();
    await p.waitForTimeout(1800);
  }
  await p.screenshot({ path: out + 'transakt-demo-full.png', fullPage: true });
  await ctx.close();
  await b.close();
})();
