# /pptx — Leitura e edição de arquivos PPTX

Use esta skill quando precisar **ler conteúdo** ou **editar texto** de arquivos `.pptx` no repositório — tipicamente os decks comerciais em `V2/propostas_e_apresentacoes/`.

---

## DEPENDÊNCIA

Biblioteca: [`python-pptx`](https://python-pptx.readthedocs.io/).

```bash
python3 -c "import pptx; print(pptx.__version__)" 2>/dev/null \
  || pip install python-pptx
```

Já instalado no ambiente atual (`1.0.2`).

---

## LEITURA — extrair texto, tabelas e notas

Script padrão (salvar como `/tmp/extract_pptx.py` ou rodar inline):

```python
from pptx import Presentation

def extract(path):
    prs = Presentation(path)
    print(f"\n=== {path} — {len(prs.slides)} slides ===")
    for i, slide in enumerate(prs.slides, 1):
        print(f"\n--- Slide {i} ---")
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in para.runs).strip()
                    if text:
                        print(text)
            if shape.has_table:
                for row in shape.table.rows:
                    print(" | ".join(c.text.strip() for c in row.cells))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                print(f"[NOTAS]: {notes}")
```

Uso:
```bash
python3 /tmp/extract_pptx.py V2/propostas_e_apresentacoes/bring_data_gen_v5.pptx
```

---

## EDIÇÃO — substituir texto preservando formatação

**Regra de ouro:** nunca recrie o `Presentation()` do zero para editar — você perde layout, fontes, cores e masters. Só modifique o `.text` dos `runs` existentes.

```python
from pptx import Presentation

def replace_text(path, mapping, out_path):
    """mapping: dict {texto_antigo: texto_novo}"""
    prs = Presentation(path)
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    for k, v in mapping.items():
                        if k in run.text:
                            run.text = run.text.replace(k, v)
    prs.save(out_path)
```

### Limitações conhecidas de `run.text`
- Se uma string estiver quebrada em múltiplos runs (ex.: uma palavra com negrito no meio), substituir em um único run não funciona. Nesse caso, inspecione `[r.text for r in para.runs]` antes.
- Alterar texto que ultrapassa a largura do placeholder **não** reajusta o layout — revise visualmente no PowerPoint/Keynote depois.
- Nunca altere tamanho de slides, masters ou layouts por código; delegue isso ao designer.

### Operações não suportadas com segurança
- Adicionar/remover slides mantendo design consistente.
- Alterar tema, cores, fontes globais.
- Editar SmartArt, gráficos complexos ou vídeos embedados.

Se o pedido for um desses, **pare e avise o usuário** — provavelmente é trabalho de editor visual.

---

## ARQUIVOS ATIVOS NO PROJETO

Decks comerciais em `V2/propostas_e_apresentacoes/` (detalhes em `/comercial`):

| Arquivo | Público |
|---|---|
| `bring_data_fin_ponta_v4.pptx` | Financeiro / assessorias |
| `bring_data_mkt_v4.pptx` | Marketing / infoprodutos (com preços) |
| `bring_data_gen_v5.pptx` | Pitch genérico / flexível |

---

## CHECKLIST ANTES DE SALVAR UM PPTX EDITADO

- [ ] Salvei em `out_path` diferente do arquivo original (não sobrescrever).
- [ ] Fiz diff do texto antes/depois (rodar `extract` nos dois e comparar).
- [ ] Avisei o usuário sobre qualquer run que não pôde ser editado.
- [ ] Verifiquei se o arquivo abre sem erro (`Presentation(out_path)` sem exceção).
