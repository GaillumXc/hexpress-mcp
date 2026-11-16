# hexpress-mcp

[English README](README.en.md) | 中文

面向 AI Agent（Kimi Code、Claude、Cursor 等）的 **NUMECA HEXPRESS/Hybrid 10.1 网格生成 MCP 服务器**。

HEXPRESS 本身不提供任何现代自动化接口，本项目驱动的是安装目录里自带、但鲜为人知的三条批处理通道——**不操控 GUI、不依赖显示器、不占许可证席位**：

1. **批划分器** — `hexpresshybridx86_64.exe <conf> [-print]`：由关键字 `.conf` 文件驱动（与 GUI 导出的 "batch configuration" 完全同格式），八叉树混合网格 / S2V 表面网格、MPI 并行；
2. **批处理脚本** — `hexpressx86_64.exe -batch -script <script.py>`：无头 Python 2.7 + 内嵌 `HXP` API（CAD 导入/导出、几何查询、布尔运算、网格生成全链路）；
3. **格式转换** — `hexpressfileconvertx86_64.exe <in> <out> -print`。

> [!IMPORTANT]
> **非官方项目，与 Siemens Digital Industries Software（原 NUMECA）无任何关系。**
> 本项目不包含、也不分发任何 HEXPRESS 软件、库或数据文件。运行时需要你在本机
> **合法安装** HEXPRESS/Hybrid 10.1 并拥有可用许可证；请遵守你的许可证协议。

## 特性

- 8 个 MCP 工具，覆盖网格生成全流程：环境探测 → 几何检查 → CAD 转存 → conf 生成 → 网格划分（含 MPI）→ 统计解析
- `run_mesh` 自动解析日志中的**单元计数与质量指标**（负雅可比、skewness、edge length、耗时），结构化返回
- 每个工具调用都是独立子进程：崩溃不传染、不驻留、不持许可证
- 工具永不抛出——所有错误以 JSON 返回，Agent 可读取自愈
- 实测案例：方盒 STL、双部件翼身组合体（命名 selection + BC 落盘验证）、**3.6 m 固定翼无人机全机模型（SolidWorks 2023 Parasolid V34）46 489 单元混合网格**

## 安装

```bash
uv venv --python 3.11 .venv
uv pip install -e .          # 或: uv pip install .
python -m hexpress_mcp --selftest   # 探测本机 HEXPRESS 安装与许可证
```

依赖：Python ≥ 3.11、[FastMCP](https://github.com/jlowin/fastmcp) ≥ 2.0、Windows（HEXPRESS 仅发布 Windows/Linux x86_64；本服务器在 Windows 10/11 实测）。

## 接入 MCP 客户端

### Kimi Code（`~/.kimi-code/mcp.json`，用户级）

```json
"hexpress": {
  "command": "D:\\path\\to\\hexpress-mcp\\.venv\\Scripts\\python.exe",
  "args": ["-m", "hexpress_mcp"],
  "cwd": "D:\\path\\to\\hexpress-mcp",
  "env": {
    "PYTHONPATH": "D:\\path\\to\\hexpress-mcp\\src",
    "PYTHONUTF8": "1",
    "HEXPRESS_DIR": "C:\\NUMECA_SOFTWARE\\hexpress101"
  }
}
```

`HEXPRESS_DIR` 可选：服务器会自动发现 `C:\NUMECA_SOFTWARE\hexpress*\bin64\hexpressx86_64.exe`，并缓存到 `%APPDATA%\hexpress-mcp\config.json`。

### Claude Desktop / 其他 stdio MCP 客户端

```json
{
  "mcpServers": {
    "hexpress": {
      "command": "D:\\path\\to\\hexpress-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "hexpress_mcp"],
      "env": { "PYTHONPATH": "D:\\path\\to\\hexpress-mcp\\src", "HEXPRESS_DIR": "C:\\NUMECA_SOFTWARE\\hexpress101" }
    }
  }
}
```

## 工具一览

| 工具 | 功能 |
| --- | --- |
| `get_status` | 安装路径、6 个可执行文件、许可证服务状态、版本探测（`hexpressview -batch -print`）、GUI 是否在运行 |
| `inspect_geometry` | 解析 STL 的 solid 名（即批划分器将生成的 selection 名），写 conf 前先查真名 |
| `convert_cad` | 用 GUI 内核的 Parasolid 桥重新导出 `.x_t/.x_b`——**修复批划分器读新版 Parasolid 传输文件时段错误（0xC0000005）的问题** |
| `generate_conf` | 生成批划分 `.conf`（BASEH、局部加密、边界条件、边界层、S2V 模式；按系统 ANSI 代码页写盘，中文路径安全） |
| `run_mesh` | 在 conf 上运行 `hexpresshybridx86_64.exe`，支持 `np>1` MPI；返回 `mesh_stats` 结构化统计 + 日志尾部 |
| `run_script` | 在 `-batch -script` 下运行 Python 2 脚本（HXP API 全量可用），wrapper 自动捕获被 HEXPRESS 吞掉的 stdout 并回传 `SCRIPT_RETURN_VALUE` |
| `convert_file` | 网格/几何格式互转（`hexpressfileconvertx86_64.exe`） |
| `launch_gui` | 启动交互式 GUI（分离进程） |

典型流程：`get_status` → `inspect_geometry` / `convert_cad` → `generate_conf` → `run_mesh` → 读 `mesh_stats`。

> [!WARNING]
> `run_mesh` 返回 `returncode: 0` **不代表成功**——NUMECA 的 `commAbort` 仍然以 0 退出。判定标准：`mesh_stats.counts.cells` 非空，且日志尾部无 `Error:` 行。工具无法替你判断网格是否满足你的工程要求，最终质量责任在使用者。

## 实战示例

### 例 1：STL 几何 + 命名 selection + 边界条件

```python
# 1. 几何里 solid 名 = selection 名，先查
inspect_geometry(input_file=r"D:\geo\wing_fuselage.stl")
# → {"solid_names": ["wing", "fuselage"], ...}

# 2. 生成 conf：翼面加密 1 级，两个部件设 SOL 壁面
generate_conf(
    input_files=[r"D:\geo\wing_fuselage.stl"],
    output_mesh="wingFuselageMesh.msh",
    base_h=0.15,
    refinements={"wing": [1, 1]},
    boundary_conditions={"wing": "SOL", "fuselage": "SOL"},
    mark_all_outer=True)

# 3. 跑网格
run_mesh(conf_file=r"...\confs\wing_fuselage.conf")
```

输出的 Fluent 网格 zone 定义里可以看到 `wall wing` / `wall fuselage`（BC 真实落盘）。完整可运行示例见 [`examples/box_demo/`](examples/box_demo)（含几何生成脚本）。

### 例 2：SolidWorks/CATIA 导出的 Parasolid 全机模型

```python
# 0. 若原始 x_t 让批划分器段错误（V33+ 传输文件常见），先转存
convert_cad(input_file=r"D:\cad\uav.x_t")   # → uav_v32.X_T

# 1. 估算特征尺度后选 base_h（见"排错"节：Surface Smoother 失败 = base_h 太大）
generate_conf(input_files=[r"D:\cad\uav_v32.X_T"],
              output_mesh="uav.msh", base_h=0.02, mark_all_outer=True)
run_mesh(conf_file=r"...\confs\mesh.conf", np=8)   # MPI 8 核
```

实测：3.6 m 固定翼、2 mm 薄特征，`base_h=0.02` → 46 489 单元（64% 六面体），最大 skewness 0.91，14 s。

### 例 3：HXP API 脚本（Python 2 语法！）

`run_script` 的脚本在 HEXPRESS 内嵌 **Python 2.7** 上执行，预加载 `HXP` 模块：

```python
igg_script_version(2.1)
HXP.import_parasolid(r"C:\work\geom.x_t")
bodies = get_all_bodies()
for b in bodies:
    print b.get_name(), "faces:", b.num_faces(), "healthy:", b.check()
HXP.export_parasolid(r"C:\work\geom_reexported.x_t")
print "SCRIPT_RETURN_VALUE", 0
```

- 脚本 stdout/stderr 被 wrapper 捕获后随结果返回（HEXPRESS 批模式自身会吞掉它们）
- `print "SCRIPT_RETURN_VALUE", 0` 是显式成功信号；未打印则按"无异常=0 / 异常=1"判定

## .conf 关键字参考（源自安装目录自带测试集）

```
INFILENAMES            <个数> 随后逐行列出路径
OUTFILENAME            <文件名>     （resultMesh.msh / out.spb.gz ...）
BASEH                  <基础单元尺寸>  （八叉树基准，必须解析最小特征！）
SUPPRESSPREFIX / MARKALLOUTER / EXACTMESHING / GENERATEFULLHEXAMESH
NUMBNDLAYERS           <n>          （粘性边界层数）
BNDLAYERTRANSITION     <0|1>
LOCALREFINEMENTDEFINITION <名> <初始加密级> <最小加密级>
BCDEFINITION           <名> <类型>    （SOL / INL / OUT / SYM ...）
GENERATES2VMESH        （表面到体积模式）
S2VPARAM GENERATESURFACEMESH MIXED   （只出表面网格）
CADIMPORTPARAM MEDIUM                （CAD 导入精度；COARSE/FINE 会报错）
CREATEALLEDGESFROMMODEL NOPREFIX
USEBINFILEVERSION 11
END
```

未列出的关键字可通过 `extra_lines` 原样透传。更多示例见安装目录
`C:\NUMECA_SOFTWARE\hexpress101\_python\_tests_db\_installations\hexpress\*.conf`。

## 排错（全部是实测踩过的坑）

| 症状 | 原因与对策 |
| --- | --- |
| `returncode 3221225477`（0xC0000005） | 批划分器读新版 Parasolid 传输文件崩溃 → 先 `convert_cad` 转存 |
| `Surface Smoother failed ... geometry might be open` | 几乎都是 **base_h 太大**，网格投影不到薄特征。按最小特征尺寸 1/5~1/10 取 base_h； drones/薄翼型建议先 0.02 试算 |
| `Warning: Geometry or mesh does not contain any selection which corresponds to: X` | conf 里的名字与几何 selection 不符 → 先用 `inspect_geometry`（STL）或在 CAD 里查看面名（Parasolid） |
| 批脚本"静默失败"、无任何输出 | Py2 编码：脚本含非 ASCII（如中文路径）必须有 `# -*- coding: utf-8 -*-`（`run_script` 自动生成）；语法必须是 Python 2 |
| conf 里中文路径变乱码、报"file not present" | `hexpresshybridx86_64` 按系统 ANSI 代码页读 conf——`generate_conf` 已用 `mbcs` 写盘；手动编辑 conf 请用 GBK/ANSI 保存 |
| `run_mesh` 报 license 错 | FLEXlm 服务未启动：以管理员运行 `C:\NUMECA_SOFTWARE\NUMECA_License_Server*\server_install.bat` |
| MPI（np>1）不起作用 | 检查安装目录 `pvm/` 是否完整；10.1 的 `-ompi -np N` 需要机器名解析正常 |

## 开发

```bash
uv pip install pytest ruff
ruff check src tests
pytest
python -m hexpress_mcp --selftest
```

- `tests/` 不依赖 HEXPRESS 安装（纯函数与错误路径），可在任意机器上跑
- 运行时数据（confs / 脚本 / 日志）写在 `%APPDATA%\hexpress-mcp\`，不进仓库
- 新增工具后：改 `server.py` → ruff → pytest → 重启 MCP 客户端会话（stdio 服务器不热加载）

## 免责声明

- 本项目为独立开源作品，**不附属于、不认可于、不受支持于** Siemens/NUMECA
- HEXPRESS、FINE、NUMECA 及其标志均为各自所有者的商标
- 按 MIT 许可证发布；商用 HEXPRESS 许可证的条款由你与软件供应商的协议约束

## 相关项目

- `xflr5-mcp` — XFLR5 翼型/机翼分析 MCP 服务器（同一作者）
- `profili-mcp` — Profili 翼型库 MCP 服务器
