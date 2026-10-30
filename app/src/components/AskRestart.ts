import { useConfirm } from "primevue/useconfirm"
import { restartApp } from "../composables/useRestart"

/** The restart behind its confirmation, for every button that offers it (the banner, the System page). */
export function useAskRestart(): () => void {
	const confirm = useConfirm()
	return () => confirm.require({
		header: "Restart the app",
		message: "The app stops and starts again, which takes about a minute. The panel keeps what it shows meanwhile.",
		icon: "mi mi-warning",
		acceptLabel: "Restart",
		rejectLabel: "Cancel",
		acceptProps: { severity: "danger" },
		accept: () => { void restartApp() },
	})
}
