# Sistema de Controlo de Ponto · BeverageCo

Sistema web profissional de controlo de ponto com reconhecimento facial para uma empresa de bebidas.

## Stack

- **Backend**: Python 3.11 + Flask 3
- **Base de dados**: SQLite (`data/controlo_ponto.db`)
- **Reconhecimento facial**: `face_recognition` + `dlib-bin` + OpenCV (headless)
- **Frontend**: Jinja2 templates + CSS puro + Chart.js (CDN) + FontAwesome (CDN)
- **Autenticação**: bcrypt + sessões Flask seguras

## Arquitetura

```
flask_app/
├── __init__.py          # Application factory + blueprint registration
├── config.py            # Settings (paths, tolerances, defaults)
├── db.py                # SQLite schema + bootstrap + seed
├── routes/
│   ├── auth.py          # /login, /logout
│   ├── kiosk.py         # /kiosk (público) + /kiosk/recognize
│   ├── admin.py         # /admin/* (gestão completa)
│   ├── employee.py      # /funcionario/* (portal pessoal)
│   └── api.py           # /api/funcionarios/<id>/face (captura facial)
├── services/
│   ├── auth_service.py        # bcrypt, login/logout, decoradores, rate-limit
│   ├── face_service.py        # encoding, identificação, snapshots
│   ├── attendance_service.py  # entrada/saída, atrasos, sessões
│   ├── salary_service.py      # cálculo automático de salários
│   ├── notification_service.py# notificações in-app (admin/funcionário)
│   └── vacation_service.py    # saldo de férias e dias úteis
├── static/css/styles.css
└── templates/{base, login, kiosk/, admin/, employee/}
data/
├── controlo_ponto.db    # criada automaticamente
└── uploads/             # snapshots faciais
main.py                  # entry point (python3 main.py)
```

## Modos do sistema

1. **Kiosk** (`/kiosk`) — interface fullscreen para tablet, ENTRADA/SAÍDA escolhida no menu, scan facial com moldura oval, som de confirmação, retorno automático.
2. **Portal funcionário** (`/funcionario/...`) — dashboard com avatar, contador de férias, notificações; registos, horário, salário, faltas, **justificações** (submeter pedido), **férias** (pedir + saldo), **perfil** (foto + password).
3. **Painel admin** (`/admin/...`) — gestão completa: funcionários (com foto), horários, registos, faltas, **justificações** (aprovar/rejeitar), **férias** (aprovar/rejeitar + saldos), salários, estatísticas, departamentos, notificações.

## Funcionalidades de comunicação

- **Notificações in-app**: sino com badge no topbar (ambos os lados). O kiosk envia notificação ao funcionário em cada entrada/saída com hora, atraso e ganho do dia. O admin é notificado em pedidos novos e tentativas de login falhadas. As alterações de horário notificam o funcionário.
- **Pedidos de justificação de falta**: funcionário submete (data + motivo); admin aprova/rejeita com resposta opcional. Aprovação cria automaticamente registos em `faltas` como justificadas.
- **Pedidos de férias**: funcionário submete período (apenas dias úteis contados); admin aprova/rejeita. Saldo anual configurável por funcionário (`dias_ferias_ano`, default 22).
- **Foto de perfil**: funcionário ou admin podem carregar imagem (PNG/JPG); aparece no topbar, dashboard e listagem de funcionários.
- **Segurança**: tentativas de login registadas em `login_attempts`; após 5 falhas em 15 min, conta bloqueada e admin notificado.

## Conta admin de demonstração

- Email: `admin@empresa.pt`
- Password: `admin123`

(Definida em `flask_app/config.py` · `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD`. Em produção usar `SESSION_SECRET` real.)

## Comandos

- Arrancar: `python3 main.py` (porta 5000)
- O workflow "Start application" trata disso automaticamente.

## Notas técnicas

- `face_recognition` usa `dlib-bin` (wheel pré-compilado) para evitar compilação.
- Encodings faciais (128-d float64) guardados como BLOB na tabela `face_encodings`.
- Tolerância padrão de comparação: `0.5` (menor = mais estrito).
- Atraso = minutos após hora marcada no `horarios` para o `dia_semana` atual.
- Salário = horas registadas × €/hora − (atrasos · €/hora) − (faltas × 8h × €/hora).
