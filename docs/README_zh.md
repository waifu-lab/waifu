# waifu

[English](https://github.com/waifu-lab/waifu/blob/main/README.md) | [中文](https://github.com/waifu-lab/waifu/blob/main/docs/README_zh.md)

一個以 Python 打造的模組化、可擴展 AI 伴侶伺服器。`waifu` 涵蓋對話式 AI 助理.

---

## Roadmap

- [ ] 多 Agent 協作編排支援
- [ ] Plugin 市集 / 套件倉庫
- [ ] Plugin 工具的 OpenAPI Schema 自動生成
- [ ] wait...

---

## 開發


**環境設置**

```bash
# 複製倉庫
git clone https://github.com/waifu-lab/waifu
cd waifu

# 安裝所有 workspace 相依套件
uv sync
```

**啟動伺服器**

```bash
# 以熱重載模式啟動
waifu start --config config.toml --reload
```

