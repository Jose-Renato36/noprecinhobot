const ICONES = { sucesso: '✓', erro: '!', info: 'i' }

export default function Toasts({ avisos, aoFechar }) {
  if (!avisos.length) return null
  return (
    <div className="toasts" role="status" aria-live="polite">
      {avisos.map((aviso) => (
        <div key={aviso.id} className={`toast toast--${aviso.tipo}`}>
          <span className="toast__icone">{ICONES[aviso.tipo] ?? 'i'}</span>
          <p>{aviso.texto}</p>
          <button onClick={() => aoFechar(aviso.id)} aria-label="Fechar aviso">
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
