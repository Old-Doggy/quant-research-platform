async (page) => {
  const result = {};
  await page.getByRole('heading',{name:'行情与研究',exact:true}).waitFor();
  await page.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden'});
  await page.frameLocator('iframe[title="portfolio_app.chart_component.quant_chart"]').frameLocator('iframe').locator('#price-pane canvas').first().waitFor();
  const frame = page.frames().find(f=>f.url()==='about:srcdoc');
  if (!frame) throw Error('K-line frame missing');
  const canvas = frame.locator('#price-pane canvas:visible').nth(1);
  await canvas.scrollIntoViewIfNeeded();
  const size = await canvas.boundingBox();
  const started = Date.now();
  await canvas.click({position:{x:size.width*.58,y:size.height*.48}});
  await page.getByText(/图上选择 \d{4}-\d{2}-\d{2}/).waitFor();
  result.klineSelection = await page.getByText(/图上选择 \d{4}-\d{2}-\d{2}/).innerText();
  result.klineRoundtripMs = Date.now()-started;
  const newFrame = page.frames().find(f=>f.url()==='about:srcdoc');
  result.frameSurvived = await newFrame.locator('#price-pane canvas').count()>0;
  await page.getByText('策略',{exact:true}).first().click();
  await page.getByRole('heading',{name:'策略研究',exact:true}).waitFor();
  await page.getByRole('button',{name:'运行研究',exact:true}).click();
  await page.locator('.stPlotlyChart').first().waitFor({timeout:30000});
  await page.locator('[data-testid="stStatusWidget"]').waitFor({state:'hidden'});
  await page.screenshot({path:'output/playwright/m0-after-strategy-result.png',scale:'css'});
  await page.getByText('收起参数',{exact:true}).click();
  await page.getByText('展开参数',{exact:true}).waitFor();
  result.collapsed = await page.getByText('研究参数',{exact:true}).count()>0;
  await page.getByText('展开参数',{exact:true}).click();
  await page.getByText('收起参数',{exact:true}).waitFor();
  result.expanded = await page.getByText('收起参数',{exact:true}).count()>0;
  await page.locator('.stPlotlyChart').first().waitFor();
  result.widths=[];
  for(const width of [1440,1280]){
    await page.setViewportSize({width,height:1000});
    await page.locator('[data-testid="stPlotlyChart"]').first().waitFor();
    result.widths.push(await page.evaluate(()=>{
      const main=document.querySelector('[data-testid="stMain"]');
      const r=document.querySelector('[data-testid="stPlotlyChart"]').getBoundingClientRect();
      return {width:innerWidth,mainWidth:main.clientWidth,scrollWidth:main.scrollWidth,chartTop:r.top,chartRight:r.right};
    }));
  }
  result.exceptions=await page.locator('[data-testid="stException"]').allTextContents();
  await page.getByText('组合',{exact:true}).first().click();
  await page.getByRole('heading',{name:'组合研究',exact:true}).waitFor();
  await page.getByRole('button',{name:'运行组合研究',exact:true}).click();
  await page.getByText('点击曲线定位持仓日期',{exact:false}).waitFor({timeout:30000});
  const curve = page.locator('[data-testid="stPlotlyChart"]').first();
  const point = curve.locator('.scatterlayer .trace:first-child .points .point').nth(10);
  const beforeDate = await page.getByText('点击曲线定位持仓日期',{exact:false}).innerText();
  await point.scrollIntoViewIfNeeded();
  await point.click({force:true});
  await page.waitForFunction(before=>Array.from(document.querySelectorAll('p')).some(p=>p.textContent.includes('点击曲线定位持仓日期') && p.textContent!==before),beforeDate);
  result.plotlySelection=await page.getByText('点击曲线定位持仓日期',{exact:false}).innerText();
  return result;
}
