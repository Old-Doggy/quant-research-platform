async (page) => {
  await page.getByText('看盘', { exact: true }).first().click();
  await page.getByText('更新行情', { exact: true }).click();
  await page.getByText('已核对原始日线 · 成交量：股 · 成交额：元 · 公司行为核验完成后开放研究', { exact: true }).waitFor();
  await page.locator('[data-testid="stStatusWidget"]').waitFor({ state: 'hidden' });
  const selectedUrl = page.url();
  await page.screenshot({ path: 'output/playwright/m2-watch-live.png', scale: 'css' });
  const frames = page.frames().filter(f => f !== page.mainFrame());
  const chart = [];
  for (const frame of frames) {
    const data = await frame.evaluate(() => ({ text: document.body.innerText.slice(0, 600), canvases: document.querySelectorAll('canvas').length }));
    if (data.canvases) chart.push(data);
  }
  await page.reload();
  await page.getByText('已核对原始日线 · 成交量：股 · 成交额：元 · 公司行为核验完成后开放研究', { exact: true }).waitFor();
  await page.locator('[data-testid="stStatusWidget"]').waitFor({ state: 'hidden' });
  const pinned = !(await page.getByRole('checkbox', { name: '跟随当前行情版本' }).isChecked());
  return { selectedUrl, restoredUrl: page.url(), pinned, chart, exceptions: await page.locator('[data-testid="stException"]').allTextContents() };
}
