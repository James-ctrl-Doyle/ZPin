// 批量栅格化：读一个任务清单 JSON，逐项把 SVG 渲染成 PNG。
// 用法: node render_all.js tasks.json
// 任务项: { svg: <svg文件路径>, out: <png输出路径>, size: <像素>
const fs = require('fs');
const path = require('path');

// resvg 装在**项目内**的 ext/build/node_modules（ZPin 的规矩：依赖一律落在 ext/build 下，
// 那个目录整个被 gitignore）。原来指工作区外的 .workbuddy 托管目录，已搬进来 ——
// 两个包都要：resvg-js 是主包，resvg-js-win32-x64-msvc 才是真正的二进制。
//
// ⚠ 目录名必须叫 node_modules（**不能**加点避开 git 的写法）：Node 的模块解析
//   只认这个标准名字，resvg-js/js-binding.js 里那句
//   require("@resvg/resvg-js-win32-x64-msvc") 就是靠它找到平台二进制包的。
//   （Python 那边的 ext/build/.pylibs 能用点前缀，是因为它由 sys.path 显式挂载。）
const NODE_MODULES = path.join(__dirname, '..', 'build', 'node_modules');
const { Resvg } = require(path.join(NODE_MODULES, '@resvg/resvg-js'));

const tasks = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const cache = new Map();

let n = 0;
for (const t of tasks) {
  if (!cache.has(t.svg)) cache.set(t.svg, fs.readFileSync(t.svg, 'utf8'));
  const resvg = new Resvg(cache.get(t.svg), {
    fitTo: { mode: 'width', value: t.size },
    background: 'rgba(0,0,0,0)',
    font: { loadSystemFonts: false },
  });
  fs.mkdirSync(path.dirname(t.out), { recursive: true });
  fs.writeFileSync(t.out, resvg.render().asPng());
  n++;
}
console.log(`rendered ${n} files`);
