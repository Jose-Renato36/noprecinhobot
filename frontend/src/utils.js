export const brl = (valor) =>
  valor === null || valor === undefined
    ? '—'
    : Number(valor).toLocaleString('pt-BR', {
        style: 'currency',
        currency: 'BRL',
        minimumFractionDigits: 2,
      })

export const dataHora = (iso) =>
  !iso
    ? '—'
    : new Date(iso).toLocaleString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })

export function tempoRelativo(iso) {
  if (!iso) return 'nunca'
  const segundos = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (segundos < 0) return 'em instantes'
  if (segundos < 60) return 'agora mesmo'
  if (segundos < 3600) return `há ${Math.floor(segundos / 60)} min`
  if (segundos < 86400) return `há ${Math.floor(segundos / 3600)} h`
  return `há ${Math.floor(segundos / 86400)} d`
}

export function contagemRegressiva(iso) {
  if (!iso) return null
  const segundos = Math.round((new Date(iso).getTime() - Date.now()) / 1000)
  if (segundos <= 0) return 'a qualquer momento'
  if (segundos < 60) return `em ${segundos}s`
  const minutos = Math.floor(segundos / 60)
  if (minutos < 60) return `em ${minutos} min`
  return `em ${Math.floor(minutos / 60)}h${String(minutos % 60).padStart(2, '0')}`
}

export const ROTULOS_STATUS = {
  aguardando: 'Aguardando',
  alvo_atingido: 'Alvo atingido',
  pausado: 'Pausado',
  erro: 'Erro na coleta',
}

// Como o scraper chegou naquele preço — da fonte mais confiável para a menos.
export const ROTULOS_FONTE = {
  aprendido: 'Seletor aprendido',
  'json-ld': 'JSON-LD (schema.org)',
  microdata: 'Microdata',
  'seletor-loja': 'Seletor da loja',
  meta: 'Meta tags (OpenGraph)',
  'json-inline': 'JSON embutido na página',
  varredura: 'Varredura do HTML',
}

export function nivelConfianca(valor) {
  if (valor === null || valor === undefined) return null
  if (valor >= 0.8) return 'alta'
  if (valor >= 0.55) return 'media'
  return 'baixa'
}
