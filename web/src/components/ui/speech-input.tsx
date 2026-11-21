"use client"

import * as React from "react"
import { VoiceButton, type VoiceButtonProps, type VoiceButtonState } from "@/components/ui/voice-button"

export interface SpeechInputProps extends Omit<VoiceButtonProps, "onPress"> {
    onSpeechStart?: () => void
    onSpeechEnd?: (blob: Blob) => void
    /**
     * Whether to auto-submit when speech ends
     * @default true
     */
    autoSubmit?: boolean
    /**
     * Enable spacebar to toggle voice recording when no input is focused
     * @default false
     */
    enableSpacebarShortcut?: boolean
}

export const SpeechInput = React.forwardRef<HTMLButtonElement, SpeechInputProps>(
    ({ onSpeechStart, onSpeechEnd, autoSubmit = true, enableSpacebarShortcut = false, ...props }, ref) => {
        const [voiceState, setVoiceState] = React.useState<VoiceButtonState>("idle")
        const mediaRecorderRef = React.useRef<MediaRecorder | null>(null)
        const recordingStartRef = React.useRef<number>(0)
        const MIN_RECORDING_DURATION_MS = 500

        // Sync local state with prop if needed, but for now local state drives the UI
        // If parent passes 'state' prop, we might want to respect it, but VoiceButton props are passed via ...props
        // so we need to be careful not to conflict. 
        // Actually, the usage in page.tsx passes 'state' prop based on external loading state.
        // We should probably merge them or let local state override during recording.
        // For now, let's assume 'state' prop handles "processing" and "error" from parent, 
        // but "recording" state is local.

        const effectiveState = voiceState === "recording" ? "recording" : (props.state || voiceState)

        const handleVoicePress = React.useCallback(async () => {
            if (voiceState === "recording") {
                // Stop recording
                if (mediaRecorderRef.current) {
                    mediaRecorderRef.current.stop()
                }
                return
            }

            try {
                onSpeechStart?.()
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
                const recorder = new MediaRecorder(stream)
                const chunks: Blob[] = []

                recorder.ondataavailable = (e) => {
                    if (e.data.size > 0) chunks.push(e.data)
                }

                recorder.onstop = () => {
                    const blob = new Blob(chunks, { type: recorder.mimeType })
                    const duration = Date.now() - recordingStartRef.current

                    if (duration >= MIN_RECORDING_DURATION_MS && blob.size >= 1000) {
                        setVoiceState("processing") // Temporary local processing state
                        onSpeechEnd?.(blob)
                        // State clearing is left to parent or timeout if not controlled
                        if (!props.state) {
                            setTimeout(() => setVoiceState("idle"), 3000)
                        } else {
                            // If parent controls state, we reset local to idle so parent state takes over
                            setVoiceState("idle")
                        }
                    } else {
                        setVoiceState("error")
                        setTimeout(() => setVoiceState("idle"), 3000)
                    }

                    stream.getTracks().forEach((track) => track.stop())
                }

                recorder.start(100)
                mediaRecorderRef.current = recorder
                recordingStartRef.current = Date.now()
                setVoiceState("recording")
            } catch (err) {
                console.error("Failed to start recording:", err)
                setVoiceState("error")
                setTimeout(() => setVoiceState("idle"), 3000)
            }
        }, [voiceState, onSpeechEnd, onSpeechStart, props.state])

        // Spacebar shortcut for voice recording
        React.useEffect(() => {
            if (!enableSpacebarShortcut) return

            const handleKeyDown = (e: globalThis.KeyboardEvent) => {
                if (e.code !== "Space") return
                const tag = document.activeElement?.tagName
                if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return
                e.preventDefault()
                handleVoicePress()
            }

            window.addEventListener("keydown", handleKeyDown)
            return () => window.removeEventListener("keydown", handleKeyDown)
        }, [enableSpacebarShortcut, handleVoicePress])

        return (
            <VoiceButton
                ref={ref}
                onPress={handleVoicePress}
                {...props}
                state={effectiveState}
            />
        )
    }
)
SpeechInput.displayName = "SpeechInput"
