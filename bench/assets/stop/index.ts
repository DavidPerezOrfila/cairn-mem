import { Plugin } from "@opencode/plugin"
import { appendFileSync, readFileSync } from "node:fs"

// Round 3 (S27): un solo empujón cuando el turno termina sin `save`. El texto está
// congelado en el protocolo (bench/ab_write_protocol.md).
const NUDGE = `Al cerrar: si esta conversación te dio una razón que no está en el código (por qué el usuario quiere el cambio, una restricción, quién consume el dato), guárdala ahora en la memoria del proyecto con \`cairn save\`, con ese porqué en \`--why\` y un \`--topic\` estable. Una sola memoria. Si no hay ninguna razón así, no hagas nada.`

function norm(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase()
}

function saves(directory: string): number {
  let text = ""
  try {
    text = readFileSync(directory + "/.cairn/events.jsonl", "utf8")
  } catch {
    return 0
  }
  let count = 0
  for (const line of text.split("\n")) {
    if (!line.trim()) continue
    try {
      if (JSON.parse(line).op === "save") count++
    } catch {
      // cola rota: el store la repara al abrir
    }
  }
  return count
}

export default Plugin.define({
  id: "cairn.stop",
  setup(ctx) {
    const directory = ctx.location.directory
    const log = directory + "/.cairn-nudge.log"
    const before = saves(directory)
    const nudged = new Set<string>()

    // El plugin vive en el servidor compartido: sin este filtro avisaría sesiones de
    // otros proyectos (medido 2026-11-21).
    const own = async (sessionID: string): Promise<boolean> => {
      try {
        const session = await ctx.session.get({ sessionID })
        return !session.parentID && norm(session.location.directory) === norm(directory)
      } catch {
        return false
      }
    }

    const controller = new AbortController()
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({
          types: ["session.execution.succeeded"],
          signal: controller.signal,
        })) {
          const sessionID = (event as { data?: { sessionID?: string } }).data?.sessionID
          if (!sessionID || nudged.has(sessionID)) continue
          nudged.add(sessionID)
          if (saves(directory) > before) continue
          if (!(await own(sessionID))) continue
          appendFileSync(log, sessionID + "\n")
          await ctx.session.prompt({ sessionID, text: NUDGE })
        }
      } catch {
        // el CLI cierra el stream; no hay nada que hacer
      }
    })()
    return () => controller.abort()
  },
})
