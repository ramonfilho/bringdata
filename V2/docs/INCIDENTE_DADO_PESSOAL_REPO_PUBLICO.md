# 202 mil e-mails num repositório público, cinco meses

Registro do incidente de 14/08/2026 e da decisão sobre até onde ir na remoção.

---

## O que estava exposto

`V2/compare_encoded.parquet`, commitado na `main` de um repositório **público**:

| | |
|---|---|
| linhas | 202.489 |
| **e-mails reais distintos** | **202.219** (99,7% em formato válido) |
| colunas de característica por pessoa | 63 |
| compradores identificáveis (e-mail + alvo de compra) | **2.636** |
| janela dos dados | 07/02/2025 a 09/04/2026 |
| entrou em | **08/03/2026**, atualizado em 14/05/2026 |
| tempo exposto | **cinco meses** |

Os outros 10 arquivos de dado versionados foram varridos e estão limpos: dois modelos
treinados, dois calibradores e cinco CSVs agregados, zero e-mail.

## Como foi encontrado

Por acaso. O arquivo aparecia no diff de um PR que ia ser mergeado por outro motivo. Já
estava lá havia meses; o PR só fez alguém olhar.

## Por que passou

Existe desde 05/08/2026 um teste que barra credencial em arquivo versionado, criado
depois do episódio da senha do Postgres. Ele procura **credencial**, e **por texto**.

Um parquet é binário e comprimido: não tem `senha=` dentro, e 6 MB não parecem um
segredo. O arquivo atravessou **dois incidentes de segurança** sem ninguém abrir.

A lição não é "faltou atenção". É que a busca por conteúdo é **cega para o formato
errado**, e por isso a guarda nova casa por formato.

## Por que a guarda nova não procura e-mail dentro dos arquivos

Foi a primeira ideia, e ela falha. Varrendo os bytes crus deste parquet, uma busca por
padrão de e-mail encontra **318** dos 202.219 reais — o resto está comprimido.

**Um teste que erra por 99,8% dá falsa tranquilidade, que é pior que teste nenhum.**

A regra segura é por categoria: arquivo de dado tabular não entra versionado,
independente do que se acredite que tem dentro. Exceções por caminho explícito, e há um
segundo teste garantindo que a lista de exceções não vire peneira larga.

---

## A decisão sobre remover do histórico

Tirar do HEAD **impede reincidência e não desfaz nada**. Enquanto o repositório for
público, o arquivo continua alcançável em commits antigos por quem souber procurar.

### O que a remoção completa envolve

Reescrever todo commit que tocou o arquivo (`git filter-repo` ou equivalente) e forçar a
publicação. Isso **troca o identificador de todos os commits** a partir de março.

### O que ela custa

| custo | detalhe |
|---|---|
| **PRs abertos quebram** | ficam baseados em commits que deixaram de existir; precisam ser refeitos |
| **Salas de trabalho quebram** | toda worktree e branch local diverge; quem estiver trabalhando precisa recomeçar |
| **Coordenação obrigatória** | não pode ser feito com outra pessoa escrevendo no repositório |
| **Objetos órfãos no GitHub** | o arquivo continua acessível por URL direta até a coleta de lixo; exige abrir chamado no suporte para forçar a purga |

### O que ela NÃO resolve

- **Quem já clonou continua com o arquivo.** Não há como recolher.
- **Cópias e arquivamentos.** Repositório público pode ter sido bifurcado, clonado por
  robô ou arquivado por serviços que preservam código aberto. Cinco meses é tempo
  suficiente.
- **Índices e caches de terceiros.**

### A leitura honesta

A remoção de histórico **reduz a superfície daqui pra frente**, não desfaz a exposição
passada. Ela vale a pena, mas o valor dela é menor do que parece, e o custo é real e
imediato.

**A ação com maior redução de risco por unidade de esforço é tornar o repositório
privado** — corta o acesso em segundos, não é destrutiva, não quebra PR nem sala de
trabalho, e deixa a decisão sobre o histórico para quando houver calma. Ficou registrada
como recomendação; a decisão de manter público por enquanto foi tomada em 14/08/2026.

### A ordem recomendada, quando for feita

1. Avisar quem estiver trabalhando e esperar as salas fecharem
2. Mergear ou anotar os PRs abertos
3. Reescrever o histórico e forçar a publicação
4. Abrir chamado no suporte do GitHub para purgar os objetos órfãos
5. Todo mundo apaga o clone local e clona de novo

---

## O que não dá para consertar

Credencial se rotaciona: troca a senha e o vazamento perde valor. **E-mail não.** As
202.219 pessoas nesse arquivo não têm como trocar o endereço delas, e a lista continua
válida para quem a tiver copiado.

É por isso que a guarda por formato é mais importante que a remoção: ela impede o
próximo, e o próximo é a única parte que ainda está sob nosso controle.

---

*Registrado em 14/08/2026. Guarda em `V2/tests/test_sem_dado_pessoal_no_repo.py`, irmã
da `test_sem_credencial_no_repo.py`.*
