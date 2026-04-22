# /sheets — Leitura e edição de Google Sheets

Use esta skill para qualquer operação em Google Sheets do projeto.

> **REGRA CENTRAL:** a planilha `bring_data_contatos` é **view**, não fonte. A fonte autoritativa é `V2/comercial/contatos.csv`. **Toda mudança de dados passa pelo CSV** via módulo de sync. Edição direta no browser exige `pull` antes do próximo `push`.

---

## FLUXO OFICIAL — `bring_data_contatos`

### Módulo: `V2/comercial/contatos_sync.py`

Encapsula schema, validação, sync bidirecional e UI kit. **Sempre usar isso** em vez de manipulação direta via `gspread` para mudanças de dados.

### Comandos

```bash
# CSV → Sheet (CSV é a fonte; escreve + reaplica UI kit)
python V2/comercial/contatos_sync.py --push

# Sheet → CSV (quando o usuário editou no browser)
python V2/comercial/contatos_sync.py --pull

# Validação sem escrita
python V2/comercial/contatos_sync.py --push --dry-run
python V2/comercial/contatos_sync.py --pull --dry-run
```

O CLI retorna exit codes não-zero em erro de schema, o que permite uso em hooks/pipelines.

### Schema (9 colunas, definido em `COLUMNS`)

| Col | Nome | Width | Observação |
|---|---|---|---|
| A | Nome | 180 | — |
| B | Tipo de empresa | 160 | — |
| C | Site | 170 | — |
| D | Email | 220 | — |
| E | Telefone | 120 | — |
| F | Copy | 400 (wrap) | mensagem completa com `Subject:` na 1ª linha |
| G | Status de envio | 130 | **dropdown + cor por linha** |
| H | Data de envio | 110 | ISO `YYYY-MM-DD` |
| I | Observações | 300 (wrap) | próxima ação / estado / notas livres |

Subtipo, Qualidade e Observações foram removidos do schema em abr/2026. Se quiser restaurar, editar `COLUMNS` em `contatos_sync.py` (a validação falha alto se o CSV não bater — proteção contra schema drift).

### Status válidos + cores de linha

| Valor | Cor |
|---|---|
| `Fechado` | verde claro |
| `Follow-up` | azul claro |
| `Enviado` | amarelo claro |
| `A enviar` (ou vazio com Nome preenchido) | vermelho claro |
| `Sem resposta` / `Reunião agendada` / `Pós-reunião` / `Proposta enviada` / `Perdido` | sem cor (no dropdown, cor neutra) |

Prioridade: Fechado > Follow-up > Enviado > A enviar. Definida em `insert_rules` em `apply_ui_kit`.

### Workflow para qualquer mudança de dados

1. **Edite o CSV** (`V2/comercial/contatos.csv`) — diretamente em editor/Cursor ou via pandas.
2. Rode `--push --dry-run` para validar schema.
3. Rode `--push` — o Sheet recebe os dados **e** o UI kit completo (freeze, cabeçalho, cores, dropdown, bordas).
4. Se você editou o Sheet no browser antes de editar o CSV, rode `--pull` primeiro para sincronizar pra baixo, faça o merge manual, e só então `--push`.

---

## AUTENTICAÇÃO

Credenciais locais em `~/.config/gcloud/application_default_credentials.json` (ADC). Bibliotecas instaladas globalmente:

- `gspread` (testado na versão `6.2.1`)
- `google-auth` (vem com gcloud)

Scopes **sempre declarar explicitamente** — ADC padrão não inclui Sheets:

```python
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
```

Skeleton de conexão (para leitura ad-hoc, não para sync):

```python
import gspread
from google.auth import default

creds, _ = default(scopes=SCOPES)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SHEET_ID)
ws = sh.worksheet("NomeDaAba")
```

Se `403 PERMISSION_DENIED`:
1. O email do ADC precisa de acesso à planilha (compartilhar como editor).
2. Conta ativa: `gcloud auth application-default print-access-token --verbosity=info` ou `~/.config/gcloud/active_config`.

---

## PLANILHAS ATIVAS

| Planilha | ID | Sync |
|---|---|---|
| `bring_data_contatos` | `1jJWKPiuFz5SbtQCkqE6CLUPn7FHe7taoQjnRelwcSvI` | Via `V2/comercial/contatos_sync.py` |

---

## OPERAÇÕES AD-HOC (inspeção rápida, não produção)

Para leitura pontual ou debug — **nunca para mudanças persistentes** (essas passam pelo sync).

### Ler intervalo / linha

```python
ws.get("A1:I10")                 # lista de listas
ws.row_values(2)                 # linha N
ws.get_all_values()              # tudo, inclusive legendas se houver
```

### Atualizar uma célula (gspread 6.x: valores primeiro)

```python
ws.update(values=[["novo valor"]], range_name="E6")
```

> Chamar na ordem antiga (`update("A1", [[...]])`) emite `DeprecationWarning`. Sempre named args.

### Localizar linha por Nome

```python
all_vals = ws.get_all_values()
row_idx = next(i for i, r in enumerate(all_vals, 1) if r and r[0] == "XP Investimentos")
```

---

## ARMADILHAS CONHECIDAS

- **`get_all_values()` trunca linhas no último elemento não-vazio.** Sempre padronizar largura: `r + [""] * (N_COLS - len(r))`.
- **`insert_rows` em sheet que já teve colunas deletadas** mistura posições — por isso todo insert produtivo passa pelo sync (que faz `clear + write` atômico).
- **Valores numéricos em colunas de texto viram float:** `"01"` vira `"1"` com `USER_ENTERED`. Use `RAW` para preservar.
- **Rate limit:** Sheets API permite ~60 requests/min por usuário. Operações em lote (`batch_update`) são bem mais baratas.
- **Status "A enviar"**: o status literal **e** o status vazio são tratados como "a enviar" pela cor de fundo. Se o dropdown força algum valor no futuro, atualizar `insert_rules`.

---

## PROTOCOLO DE ESCRITA (obrigatório)

1. **Toda mudança de dados em `bring_data_contatos` passa pelo CSV + `--push`.** Não editar células via gspread diretamente exceto em casos de investigação.
2. **Antes do `push`:** rodar `--dry-run` para validar schema (nomes de colunas, status no enum).
3. **Se você deletar ou renomear colunas no browser:** a próxima execução do sync falha alto com `SchemaError`. Fix: edite `COLUMNS` em `contatos_sync.py` + ajuste o CSV.
4. **Datas:** ISO (`2026-04-21`) no CSV. O `value_input_option="USER_ENTERED"` converte para data no Sheets.
5. **Após push:** verificar visualmente no browser antes de seguir — UI kit é aplicado em blocos (freeze, cores, bordas) e eventual inconsistência aparece.

---

## CHECKLIST ANTES DE QUALQUER ESCRITA

- [ ] Mudança vai para o CSV, não direto no Sheet?
- [ ] `--dry-run` passou sem `SchemaError`?
- [ ] Status novos usados estão no enum `STATUS_VALUES`?
- [ ] Datas no formato ISO?
- [ ] Após push, visualizei o Sheet no browser e está correto?
