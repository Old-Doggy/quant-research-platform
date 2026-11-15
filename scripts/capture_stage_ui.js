async (page) => {
  const root = 'output/playwright';
  const stage = 'm1-final';
  const routes = ['watch', 'factors', 'strategy', 'portfolio', 'data', 'experiments', 'showcase'];
  const labels = ['看盘', '因子', '策略', '组合', '数据', '实验', '作品'];
  const titles = ['行情与研究', '因子研究', '策略研究', '组合研究', '数据中心 / Data Center', '实验记录', '研究作品与工程实践'];
  const results = [];
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (let i = 0; i < routes.length; i++) {
    await page.getByText(labels[i], { exact: true }).first().click();
    await page.waitForFunction(id => (new URL(location.href).searchParams.get('workspace') || 'watch') === id, routes[i]);
    await page.getByRole('heading', { name: titles[i], exact: true }).waitFor();
    await page.locator('[data-testid="stStatusWidget"]').waitFor({ state: 'hidden' });
    const exceptions = await page.locator('[data-testid="stException"]').allTextContents();
    await page.screenshot({ path: `${root}/${stage}-${routes[i]}.png`, scale: 'css' });
    results.push({ route: routes[i], title: await page.locator('h1').first().innerText(), exceptions });
  }
  return results;
}
