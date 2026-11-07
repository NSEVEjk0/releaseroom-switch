import {test,expect} from "@playwright/test";
import {mkdir} from "node:fs/promises";
test("reference evidence, stale approval and checked staging artifact are inspectable",async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/');
 await expect(page.getByText(/Interactive example · Review a page change/)).toBeVisible();
 await page.getByRole('button',{name:'Try earlier approval',exact:true}).click();
 await expect(page.getByText('That approval belongs to the earlier revision.',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Back to current release',exact:true}).click();
 await page.getByRole('button',{name:'Verify the example evidence',exact:false}).click();
 await expect(page.getByText('✓ Release evidence verified.',{exact:true})).toBeVisible();
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Download example evidence',exact:false}).click();expect((await download).suggestedFilename()).toMatch(/\.json$/);
 const newPage=page.waitForEvent('popup');await page.getByRole('link',{name:'Open approved example page',exact:false}).click();const staging=await newPage;
 await expect(staging.getByRole('link',{name:'Join the build night',exact:false})).toBeVisible();await staging.close();expect(errors).toEqual([]);
});
test("private live releases reject anonymous access and mobile fits",async({page,request})=>{
 const config=await (await request.get('/api/config')).json();
 expect((await request.get('/api/releases')).status()).toBe(config.deployment==='preview'?503:401);
 await page.goto('/');await expect(page.getByText(config.deployment==='preview'?'Explore the release workflow':'Live Switch connection pending',{exact:true})).toBeVisible();
 await mkdir('reports',{recursive:true});await page.screenshot({path:'reports/releaseroom-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'reports/releaseroom-mobile.png',fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});
