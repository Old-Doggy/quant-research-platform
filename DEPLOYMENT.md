# Publishing and Deployment

This directory is the standalone public portfolio package. It is intentionally separate from the private development workspace and its Git history.

## Run Locally

The application entry point is `streamlit_app.py`. Runtime dependencies are listed in `requirements.txt`, and Python 3.12 is the baseline version. The default screen uses synthetic data and requires no environment variables, account, broker connection, or external market-data service.

The public package does not include the private research workspace. Do not set private-mode environment variables when running this directory.

## GitHub Publishing

Only this directory should be pushed to the public repository. Do not push the original workspace, reuse its Git history, or add raw uploads, virtual environments, caches, credentials, research outputs, or account files.

Keep the repository private until the owner has reviewed the complete file list and confirmed that the generic code and synthetic datasets may be exposed. Add a `LICENSE` file only after the owner chooses the license. Without a license, reuse and redistribution should not be assumed.

The included workflow checks the public test suite on Ubuntu and Windows with Python 3.12 and 3.13. A green local test run does not replace reviewing the remote workflow result after each push.

## Hosting

After the owner confirms a hosting platform and completes its account authorization, select `streamlit_app.py` as the application entry point, use Python 3.12, and install from `requirements.txt`.

Do not add private service configuration to the hosted project. The owner completes all platform authorization steps; passwords and access tokens should never be shared in chat.

Before describing a hosted demo as available, verify the real URL, all four pages, example strategies, charts, and file-upload behavior. No hosted demo URL is included until that verification is complete.

## Data Handling

Bundled CSV files are synthetic and are not historical securities data. Uploaded files are processed in the active application session and are not intentionally written to disk by the application. Hosting providers may have their own retention, logging, and data-processing policies, so sensitive files should be analyzed only in a controlled local environment.

---

# 发布与部署（中文）

本目录是独立的公开作品包，与私人开发工作区及其 Git 历史分离。

## 本地运行

应用入口为 `streamlit_app.py`，运行依赖写在 `requirements.txt` 中，基准 Python 版本为 3.12。默认页面使用合成数据，不需要环境变量、账户、券商连接或外部行情服务。

公开包不包含私人研究工作台。运行本目录时不要设置私人模式相关的环境变量。

## GitHub 发布

只应将本目录推送到公开仓库。不要推送原始工作区、复用原 Git 历史，也不要加入原始上传文件、虚拟环境、缓存、凭证、研究结果或账户文件。

在所有者检查完整文件清单并确认通用代码与合成数据可以公开之前，仓库应保持 Private。许可证需要由所有者选择后再添加；没有许可证时，不应默认内容可以自由复用或再分发。

仓库内置工作流会在 Ubuntu 和 Windows 上检查 Python 3.12 与 3.13 的公开测试。每次推送后仍应检查远程工作流结果，不能只依赖本地测试。

## 托管

所有者确认托管平台并完成账户授权后，选择 `streamlit_app.py` 作为入口，使用 Python 3.12，并从 `requirements.txt` 安装依赖。

不要把私人服务配置加入托管项目。平台授权由所有者自行完成，密码和访问令牌不应在聊天中提供。

在把线上 Demo 写入项目说明之前，应验证真实 URL、四个页面、示例策略、图表和文件上传流程。验证完成前不放置线上地址。

## 数据处理

仓库自带 CSV 全部是合成数据，不是证券历史行情。上传文件由当前应用会话处理，应用本身不会主动写入磁盘。托管平台可能有自己的留存、日志和数据处理政策，因此敏感文件只能在受控的本地环境中分析。
