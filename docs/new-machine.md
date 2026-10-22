# Стенд на новом компьютере

Как перенести стенд на другой Mac и проверить, что он даёт те же условия. Код берётся из приватного репозитория,
закреплённые пакеты и исходные материалы — из архива переноса, а всё, что зависит от машины (паспорт окружения,
калибровка, пробы моделей и харнесов), создаётся заново.

## 1. Что поставить вручную

| Что | Проверка | Как поставить |
|---|---|---|
| Mac на Apple silicon, macOS | `uname -m` → `arm64` | — |
| Rosetta 2 (клиент 1С собран под x86_64) | `arch -x86_64 /usr/bin/true` | `softwareupdate --install-rosetta --agree-to-license` |
| 1С:Предприятие 8.3.27.2074 с лицензией | `/opt/1cv8/8.3.27.2074/1cv8` существует | дистрибутив платформы для macOS |
| Homebrew: Python 3.12, Java 21, gh | `/opt/homebrew/bin/python3.12`, `/opt/homebrew/opt/openjdk@21/bin/java` | `brew install python@3.12 openjdk@21 gh` |
| Claude Code 2.1.290 | `~/.local/bin/claude --version` | `curl -fsSL https://claude.ai/install.sh \| bash -s 2.1.290` |

Codex CLI 0.162.1 ставить не нужно: точная копия клиента приезжает в архиве (`.local/clients/codex-0.162.1`).

## 2. Код и архив переноса

На рабочей машине собрать архив (≈1,5 ГБ; пакеты всех харнесов, клиент Codex, `.local/sources`, квитанция проверки
сборки Unica 0.12.3):

```sh
/opt/homebrew/bin/python3.12 tools/machine_bundle.py pack --output .local/bundles/stand-bundle.tar.gz
```

На новой машине:

```sh
gh auth login
gh repo clone zeegin/1c-agent-exam-benchmark
cd 1c-agent-exam-benchmark
/opt/homebrew/bin/python3.12 tools/machine_bundle.py setup --bundle ~/Downloads/stand-bundle.tar.gz
```

`setup` по шагам:

1. проверяет всё из таблицы выше;
2. распаковывает архив в `.local/` (ничего не перезаписывает) и сверяет каждый файл с манифестом архива;
3. сверяет каждый пакет харнеса с его профилем в `profiles/` (хеш манифеста пакета, коммит релиза) и версию Codex;
4. создаёт паспорт окружения `.local/environment-verified-v1/`: восстановление каркаса в две базы, выгрузка,
   прикладная проба, сброс, отрицательный сценарий с повреждённым `.dt`;
5. проверяет, что конфигуратор 1С работает внутри песочницы решающего агента со своим кэшем;
6. калибрует грейдер в настоящей 1С (около 50 минут) — `.local/calibration/accepted-<дата>/`.

Калибровка — дело владельца, участники её не видят: у них на стенде короткая проверка
грейдера. После изменения только логики вердиктов полная калибровка не нужна:
`python tools/replay_calibration.py` сверяет код наблюдений с последней полной калибровкой,
делает один проверочный прогон в 1С и пересчитывает её сохранённые наблюдения новым
грейдером (минуты вместо часа). Полная нужна, если изменились генерация вариантов или код
наблюдателя — инструмент об этом скажет. После изменения правил присланные результаты
пересчитываются централизованно (`tools/recheck_community.py`).

Если шаг не проходит, `setup` останавливается и пишет, что поставить или исправить. Повторный запуск без `--bundle`
продолжает с проверки пакетов.

## 3. Учётные данные

- Codex: `~/.codex/auth.json` — войти в Codex CLI под аккаунтом бенчмарка
  (`.local/clients/codex-0.162.1/.../bin/codex login`).
- Claude Code: долгоживущий токен подписки, без вставки в чат и без вывода на экран:

  ```sh
  mkdir -p ~/.config/1c-exam-bench
  ~/.local/bin/claude setup-token        # показывает токен
  pbpaste > ~/.config/1c-exam-bench/claude-oauth-token   # после копирования токена
  chmod 600 ~/.config/1c-exam-bench/claude-oauth-token
  ```

Стенд передаёт токен только в окружение процесса Claude Code и никогда не пишет его в доказательства.

## 4. Пробы

Пробы доказывают, что модель, клиент и харнес работают на этой машине; планы прогонов без них не создаются.
По одной пробе на каждую пару «агент × харнес»; план пробы создаётся автоматически (`--client`):

```sh
for client in claude codex; do
  for harness in none unica-0.13.0 unica-0.12.3 shirokov-skills mcp-toolkit-1.9.0 bsl-ls-1.1.0-rc.6 \
                 bsl-analyzer-0.3.2 rlm-tools-bsl-1.43.0 code-index-1.9.0; do
    /opt/homebrew/bin/python3.12 tools/probe_harness.py --client $client --harness $harness \
      --run-id $client-$(echo $harness | tr . -)-probe-$(date +%Y%m%d)
  done
done
```

Квитанция проверки сборки Unica 0.12.3 приезжает в архиве; на новой машине её стоит подтвердить заново.

## 5. Прогоны и сайт

Планы — `tools/create_run_plan.py` с новой калибровкой и пробами этой машины; кампания —
`tools/run_exam_campaign.py --campaign <каталог>`. Сайт результатов: `./site/start.sh` (порт 8879).

Окно 1С с обработкой MCP Toolkit во время его прогонов открывается на экране — это нормально.
