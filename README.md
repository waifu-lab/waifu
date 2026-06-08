# waifu
[English](https://github.com/waifu-lab/waifu/blob/main/README.md) | [Chinese](https://github.com/waifu-lab/waifu/blob/main/docs/README_zh.md)
A modular, extensible AI companion server built with Python. `waifu` covers conversational AI assistants.

---

## Roadmap

- [ ] Support for multi-agent collaboration and orchestration
- [ ] Plugin marketplace / package repository
- [ ] Automatic generation of OpenAPI schemas for plugin tools
- [ ] wait...

---

## Development


**Setup**

```bash
# Clone the repo
git clone https://github.com/waifu-lab/waifu
cd waifu

# Install all workspace dependencies
uv sync
```

**Running**

```bash
# Start the server with hot reload
waifu start --config config.toml --reload
```

