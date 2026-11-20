# mihomo-docker

填写订阅地址后，容器首次启动自动下载配置，之后每 6 小时刷新。新配置通过校验后热加载，并保存到 `data` 卷中的 `/data/config.yaml`。下载或校验失败时继续使用已有配置。

## 启动

在 `compose.yaml` 的 `services.mihomo.environment` 下，将订阅地址填入 `SUB_URL`。保留值两侧的引号。订阅地址应返回完整的 Mihomo YAML。`MIHOMO_SECRET` 可以留空或省略，此时面板和控制 API 无需鉴权。需要鉴权时，可用 `openssl rand -hex 32` 生成密钥并填入 `MIHOMO_SECRET`。

Compose 使用 `ghcr.io/sdrpsps/mihomo-docker:latest`。使用私有镜像时，先用具备 `read:packages` 权限的 GitHub 个人访问令牌登录 `ghcr.io`。首次启动或更新镜像时执行：

```sh
docker compose pull
docker compose up -d --wait
```

- **Web 面板** `http://127.0.0.1:9090/ui/`。首次连接时使用后端地址 `http://127.0.0.1:9090`，按 Compose 中的设置填写或留空密钥。
- **代理** `127.0.0.1:7890`，支持 HTTP 和 SOCKS5。两个端口默认只绑定 Docker 宿主机的回环地址。

通过 `docker compose logs --tail=50 mihomo` 查看启动和订阅刷新日志。代理可用 `curl --noproxy '' --proxy http://127.0.0.1:7890 https://example.com/` 验证。若需调整刷新间隔，可编辑 `compose.yaml` 中的 `SUB_INTERVAL`，单位为秒。

## GitHub Actions 构建

在仓库中打开 **Actions → Build and publish container → Run workflow**。每次运行都会查询 Mihomo 和 Zashboard 的最新稳定发行版，下载并校验文件，再用同一组版本构建 `linux/amd64` 和 `linux/arm64`。GitHub Actions 使用 `GITHUB_TOKEN` 将镜像发布到 `ghcr.io/<owner>/<repo>`，生成 `run-<运行编号>-<尝试次数>` 标签，从默认分支运行时同时更新 `latest`。

可以用 `docker compose exec -T mihomo cat /usr/share/mihomo-zashboard/versions` 查看镜像打包的版本。

## 上游版本与许可证

| 已验证的上游版本 | 本项目采用的内容 | 许可证核对 |
| --- | --- | --- |
| Glash `v2.2.8` | 参考本地配置、订阅校验、热加载与失败回退的工作流 | 在该发布标签中未找到 `LICENSE`，项目元数据未声明许可证。此处独立实现管理器。 |
| Mihomo `v1.19.34` | 官方 `linux/amd64` v1 或 `linux/arm64` 二进制 | 发行标签内的 `LICENSE` 为 GPL-3.0。 |
| Zashboard `v3.30.0` | 官方 `dist-no-fonts.zip`，使用系统字体显示正文 | 发行标签内的 `LICENSE` 为 MIT，保留发布包的 `THIRD_PARTY_NOTICES.md`。 |

构建时按 GitHub 发布的 SHA-256 校验发布包，并按发行标签的 Git 文件校验值核对许可证。最终镜像使用 UPX 压缩 Mihomo，打包 Zashboard 的 `dist-no-fonts.zip`，并省去 Python 预编译字节码。镜像内的许可证位于 `/usr/share/licenses/mihomo-zashboard/`，面板第三方声明位于 `/opt/zashboard/THIRD_PARTY_NOTICES.md`。如果向他人分发镜像，按所用版本的许可证处理源码和声明。

- Glash 工作流见 [v2.2.8 文档](https://github.com/gangz1o/clash4docker/tree/v2.2.8)。
- Mihomo 见 [发布包及源码](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.34)、[标签许可证](https://github.com/MetaCubeX/mihomo/blob/v1.19.34/LICENSE)及[配置重载实现](https://github.com/MetaCubeX/mihomo/blob/v1.19.34/hub/route/configs.go)。
- Zashboard 见 [发布包](https://github.com/Zephyruso/zashboard/releases/tag/v3.30.0)、[标签许可证](https://github.com/Zephyruso/zashboard/blob/v3.30.0/LICENSE)及[同源自动检测文档](https://github.com/Zephyruso/zashboard/tree/v3.30.0#automatic-backend-connection)。

## 可选本地配置

改用本地文件时，将 `SUB_URL` 留空，并在 `mihomo` 服务的 `volumes` 下添加 `./config.yaml:/input/config.yaml:ro`。源文件需允许容器 UID `10001` 读取。
