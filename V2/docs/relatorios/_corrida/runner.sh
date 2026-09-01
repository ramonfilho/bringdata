#!/bin/bash
# Reconstrói os lançamentos fechados pela máquina canônica (régua de produção atual,
# histórico de criativo point-in-time), em pasta durável. Sequencial em 2 fios: o
# pg8000 derruba conexão sob mais concorrência (DEV21 quebrou com 3 em 24/08).
cd /Users/ramonmoreira/Desktop/bring_data/V2 || exit 1
export LAUNCHES_SOURCE=table
run() {
  lf="$1"
  mkdir -p "docs/relatorios/_corrida/$lf"
  python3 scripts/relatorio_lancamento.py --lf "$lf" --sem-etl --piso-gasto 0.01 \
    --out "docs/relatorios/_corrida/$lf" > "docs/relatorios/_corrida/$lf.log" 2>&1
  echo "$lf exit=$?"
}
export -f run
printf "%s\n" LF56 LF57 LF58 LF59 LF60 LF61 LF62 LF63 DEV21 | xargs -P 2 -n 1 -I{} bash -c 'run {}'
echo "FIM $(date)"
