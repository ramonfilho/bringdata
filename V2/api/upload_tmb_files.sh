#!/bin/bash
# =============================================================================
# Script de Upload - Arquivos TMB para Cloud Storage
# =============================================================================
#
# Descrição: Faz upload dos arquivos TMB para o bucket de validação
# Uso: ./upload_tmb_files.sh [--fechamento FILE] [--pos-devolucoes FILE]
#
# Exemplo:
#   ./upload_tmb_files.sh \
#     --fechamento tmb_semana_passada.xlsx \
#     --pos-devolucoes tmb_duas_semanas_atras.xlsx
#
# =============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# =============================================================================
# IMPORTAR BIBLIOTECAS COMPARTILHADAS
# =============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Importar funções compartilhadas (cores, print_*)
source "$SCRIPT_DIR/lib/common.sh"

# =============================================================================
# VARIÁVEIS
# =============================================================================

BUCKET_NAME="smart-ads-validation-reports"
BUCKET_PATH="vendas"

FILE_FECHAMENTO=""
FILE_POS_DEVOLUCOES=""

# =============================================================================
# FUNÇÕES
# =============================================================================

usage() {
    echo "Uso: $0 [OPTIONS]"
    echo ""
    echo "Faz upload de arquivos TMB para Cloud Storage"
    echo ""
    echo "Opções:"
    echo "  --fechamento FILE       Arquivo TMB da semana passada (fechamento)"
    echo "  --pos-devolucoes FILE   Arquivo TMB de 2 semanas atrás (pós-devoluções)"
    echo "  -h, --help              Mostrar esta mensagem"
    echo ""
    echo "Exemplos:"
    echo "  # Upload ambos arquivos"
    echo "  $0 --fechamento tmb_19-25jan.xlsx --pos-devolucoes tmb_12-18jan.xlsx"
    echo ""
    echo "  # Upload apenas fechamento"
    echo "  $0 --fechamento tmb_19-25jan.xlsx"
    echo ""
    echo "  # Upload apenas pós-devoluções"
    echo "  $0 --pos-devolucoes tmb_12-18jan.xlsx"
    exit 1
}

parse_arguments() {
    if [ $# -eq 0 ]; then
        usage
    fi

    while [[ $# -gt 0 ]]; do
        case $1 in
            --fechamento)
                FILE_FECHAMENTO="$2"
                shift 2
                ;;
            --pos-devolucoes)
                FILE_POS_DEVOLUCOES="$2"
                shift 2
                ;;
            -h|--help)
                usage
                ;;
            *)
                print_error "Argumento desconhecido: $1"
                usage
                ;;
        esac
    done
}

validate_file() {
    local file="$1"
    local label="$2"

    if [ ! -f "$file" ]; then
        print_error "$label: Arquivo não encontrado: $file"
        exit 1
    fi

    # Verificar se é .xlsx
    if [[ ! "$file" =~ \.xlsx$ ]]; then
        print_error "$label: Arquivo deve ser .xlsx"
        exit 1
    fi

    local size=$(du -h "$file" | cut -f1)
    print_success "$label: $file ($size)"
}

upload_file() {
    local local_file="$1"
    local remote_name="$2"
    local label="$3"

    print_info "Fazendo upload de $label..."
    print_info "  Origem: $local_file"
    print_info "  Destino: gs://$BUCKET_NAME/$BUCKET_PATH/$remote_name"

    gsutil cp "$local_file" "gs://$BUCKET_NAME/$BUCKET_PATH/$remote_name" || {
        print_error "Falha no upload de $label"
        return 1
    }

    print_success "$label enviado com sucesso!"
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    parse_arguments "$@"

    # Banner
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                                                                ║"
    echo "║        Smart Ads - Upload de Arquivos TMB (Cloud Storage)     ║"
    echo "║                                                                ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""

    # Validar arquivos
    print_header "VALIDAÇÃO DE ARQUIVOS"

    if [ -n "$FILE_FECHAMENTO" ]; then
        validate_file "$FILE_FECHAMENTO" "Fechamento"
    fi

    if [ -n "$FILE_POS_DEVOLUCOES" ]; then
        validate_file "$FILE_POS_DEVOLUCOES" "Pós-Devoluções"
    fi

    if [ -z "$FILE_FECHAMENTO" ] && [ -z "$FILE_POS_DEVOLUCOES" ]; then
        print_error "Nenhum arquivo fornecido"
        usage
    fi

    echo ""

    # Upload
    print_header "UPLOAD PARA CLOUD STORAGE"

    if [ -n "$FILE_FECHAMENTO" ]; then
        upload_file "$FILE_FECHAMENTO" "tmb_fechamento.xlsx" "Fechamento"
        echo ""
    fi

    if [ -n "$FILE_POS_DEVOLUCOES" ]; then
        upload_file "$FILE_POS_DEVOLUCOES" "tmb_pos_devolucoes.xlsx" "Pós-Devoluções"
        echo ""
    fi

    # Verificar uploads
    print_header "VERIFICAÇÃO"

    print_info "Arquivos no Cloud Storage:"
    gsutil ls -lh "gs://$BUCKET_NAME/$BUCKET_PATH/tmb_*.xlsx" 2>/dev/null || {
        print_warning "Nenhum arquivo TMB encontrado no bucket"
    }

    echo ""
    print_success "Upload concluído com sucesso! 🎉"
    echo ""
}

# Executar
main "$@"
