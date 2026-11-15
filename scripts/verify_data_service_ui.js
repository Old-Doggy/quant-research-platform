async (page) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.getByRole('tab', { name: '覆盖与版本', exact: true }).click();
  const chart = page.locator('[data-testid="stPlotlyChart"]').first();
  await chart.locator('.point').first().click({ force: true });
  await page.getByText('600000.SH · 2025-01-02', { exact: true }).waitFor();
  await page.locator('[data-testid="stStatusWidget"]').waitFor({ state: 'hidden' });
  const data = await page.locator('.js-plotly-plot').evaluateAll(nodes => nodes.map(n =>
    n._fullData.map(t => ({ type: t.type, x: Array.from(t.x || []), y: Array.from(t.y || []), customdata: t.customdata }))));
  const detail = await page.locator('[data-testid="stDataFrame"]').count();
  await page.screenshot({ path: 'output/playwright/m2-coverage-selected.png', scale: 'css' });
  await page.getByText('表格', { exact: true }).click();
  await page.getByRole('tab', { name: '来源', exact: true }).click();
  await page.screenshot({ path: 'output/playwright/m2-data-sources.png', scale: 'css' });
  await page.getByRole('tab', { name: '文件导入', exact: true }).click();
  await page.getByRole('button', { name: '使用当前数据，进入质量检查' }).waitFor();
  await page.screenshot({ path: 'output/playwright/m2-data-import.png', scale: 'css' });
  return { data, detail, exceptions: await page.locator('[data-testid="stException"]').allTextContents() };
}
