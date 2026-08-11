// Marca do NoPrecinhoBot: uma etiqueta de preço.
//
// Desenhada em SVG e não em emoji porque emoji não é identidade — o 🏷️ é
// renderizado pela fonte do sistema e muda de desenho entre Windows, Android e
// iPhone. Aqui a forma é sempre a mesma, herda a cor do CSS via currentColor e
// escala sem borrar.
export default function Etiqueta({ className = 'marca__etiqueta' }) {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M17.6 3.5H6.2a2.7 2.7 0 0 0-2.7 2.7v11.4c0 .7.3 1.4.8 1.9l10.2 10.2a2.7 2.7 0 0 0 3.8 0l9.3-9.3a2.7 2.7 0 0 0 0-3.8L19.5 6.4a2.7 2.7 0 0 0-1.9-.8Z" />
      <circle cx="10.4" cy="10.4" r="2.3" fill="currentColor" stroke="none" />
    </svg>
  )
}
