/* PS5 Home Screen Recorder - homebrew launcher entry.
 * Launches the PBS hardware H.264 encoder (stream on port 9999). */
async function main() {
    const PAYLOAD = window.workingDir + '/PS5Recorder.elf';

    return {
        mainText: "Home Recorder",
        secondaryText: 'Capture home screen to /data/pbs/recordings',
        onclick: async () => {
            return { path: PAYLOAD };
        }
    };
}
