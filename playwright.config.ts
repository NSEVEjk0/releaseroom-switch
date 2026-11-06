import {defineConfig} from "@playwright/test";
export default defineConfig({testDir:"tests/browser",timeout:30_000,workers:1,use:{baseURL:process.env.RELEASEROOM_BASE_URL||"http://127.0.0.1:8090",viewport:{width:1440,height:1000},trace:process.env.RELEASEROOM_BASE_URL?"off":"retain-on-failure"},
webServer:process.env.RELEASEROOM_BASE_URL||process.env.RELEASEROOM_UI_FIXTURES?undefined:{command:"python3 -m releaseroom.cli serve",url:"http://127.0.0.1:8090",timeout:20_000,reuseExistingServer:false}});
