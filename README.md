# Single-channel occipital EEG for a password selection BCI based on steady-state visual evoked potentials (SSVEP)

## Required components and downloads

* **EXG Pill by Upside Down Labs**. An instrumentation amplifier designed for recording small biopotential signals such as EEG, EMG, and ECG.

* **2x Arduino / Raspberry Pi / compatible microcontroller board**. One board is used to acquire the analog EEG signal from the EXG Pill and transmit the data to the computer. The second board is used to control the LEDs that generate the flickering visual stimuli.

* **PsychoPy**. Used as the central software environment for the entire SSVEP BCI. It generates the frame-locked visual stimuli, controls the calibration procedure, acquires EEG data through the serial connection, records stimulus and experimental markers, and runs the real-time BCI interface. It is used because it provides precise synchronization with the monitor refresh cycle while also allowing everything else to be handled within a single program.

# Electrode placement

Electrode placement followed the international 10–20 system, with the recording electrode positioned at O1 or O2 over the occipital region, where the visual processing takes place. The approximate electrode locations can be seen in the figure below left (Malmivuo & Plonsey, 1995). The reference electrode was placed over the mastoid process behind the ear. 

<img width="500" height="260" alt="Screenshot 2026-09-10 185955" src="https://github.com/user-attachments/assets/46327836-8d41-4668-891e-65516f1de4aa" /> <img width="250" height="260" alt="image" src="https://github.com/user-attachments/assets/9d4c7b41-2dbd-446d-94d0-1484d58bf33b" />

# Calibration stimulus generation and timing

Visual stimulation frequencies in approximately the 6–12 Hz range have been reported to produce relatively strong SSVEP responses, making this range suitable for a low-channel-count EEG system (Hamidi Shishavan et al., 2024). Initial testing therefore used frequencies that could be generated from an integer number of display frames on a 60 Hz monitor. Frequencies of 6.67, 7.50, 8.57, 10 and 12 Hz correspond to 9, 8, 7, 6 and 5 frames per flicker cycle, respectively. In the current system, three stimuli are used: 8.57, 10 and 12 Hz. These frequencies gave the highest accuracy for my setup. Their timing is generated directly from the monitor refresh cycle, not from software timers. 

At a nominal 60 Hz refresh rate, each displayed frame lasts approximately 16.7 ms. The stimulus frequency is therefore determined by the number of frames assigned to one complete flicker cycle. For example, the 10 Hz stimulus uses six display frames per cycle. PsychoPy prepares the contents of the next frame in advance, and the new frame is then presented at the next screen refresh using win.flip(). The flicker itself is generated using an exact frame counter. For every displayed frame, the program determines the frame’s position within the current flicker cycle and sets the active stimulus to either white or black accordingly. During calibration, the three stimuli are presented sequentially.

Only one target flickers at a time. The participant continues looking at the instructed target throughout the whole trial, including periods in which one of the other targets is flickering. This provides both "attended" and "unattended" EEG examples for every stimulation frequency, which are later used to calibrate the CCA-based classifier. Full-screen presentation is used because accurate visual-stimulus timing depends on synchronizing PsychoPy's screen updates with the monitor's vertical refresh. In full-screen mode, win.flip() can be synchronized reliably with the display refresh, producing frame intervals close to the expected 16.7 ms on the 60 Hz monitor.

During earlier testing in windowed mode, measured frame intervals were approximately 20–28 ms and were substantially less stable. In windowed operation, presentation timing is additionally affected by the operating system's desktop compositor, making precise frame-by-frame stimulation less reliable. Originally, EEG acquisition was handled by separate applications alongside PsychoPy. However, opening the full-screen PsychoPy stimulus interfered with these applications and caused recording connections to be lost. The current implementation therefore performs the experiment within a single PsychoPy program: it presents the visual stimuli, receives the EEG data through the serial connection, and writes both EEG samples and experimental markers directly to CSV files.

Stimulus timing markers are tied to actual screen presentation. FLICKER_ON, FLICKER_OFF, and individual flicker-state transitions are scheduled using win.callOnFlip(). Therefore, their timestamps correspond to the screen flip on which the visual change is actually presented rather than to the earlier point in the Python code at which the command was issued. The calibration screen used during the experiment is shown below.

## SSVEP classifier calibration

Calibration is required because the absolute CCA scores produced by the EEG are specific to the participant, recording conditions, electrode placement, and stimulation frequency. A raw CCA score therefore cannot directly indicate whether a stimulus is being attended. The calibration analysis consists of four stages: EEG preprocessing, CCA feature extraction, classifier calibration, and cross-validation. First, the recorded EEG from the selected occipital channel is **band-pass filtered between 4 and 30 Hz**. For every flicker period, the first 0.25 s after stimulus onset is discarded to avoid including the initial visual transient.

The feature used for classification is the CCA score. For each LEFT, SELECT, or RIGHT flicker period, the corresponding EEG window is compared with synthetic sine and cosine reference signals at the stimulus frequency and its second harmonic. **Canonical Correlation Analysis (CCA)** reduces the EEG window to a single value between 0 and 1 describing how strongly the EEG follows the expected SSVEP pattern. Therefore, each flicker epoch produces one CCA score, and each complete calibration trial produces three CCA scores in total: one for LEFT, one for SELECT, and one for RIGHT.

Classifier then determines what these CCA features look like when each stimulus is attended and when it is unattended. For every stimulus, the program calculates the **mean attended CCA score, mean unattended CCA score, and their pooled standard deviation**. A new CCA score is standardized relative to this model to produce an **attention-evidence score**. This describes whether the measured response is closer to the attended or unattended calibration data. The resulting attention-evidence values are compared, and the command with the largest value is selected as LEFT, SELECT, or RIGHT.

Leave-one-trial-out cross-validation was used to evaluate classifier performance for each candidate EEG window length and to select the shortest window achieving the required accuracy. Finally, the classifier parameters are recalculated using all calibration trials and saved together with the selected window length, stimulation frequencies, filtering parameters, and CCA settings in SSVEP_sequential_classifier_config.json.

## Real-time control of the password selection BCI


**Reference**

Hamidi Shishavan, H., Roy, R., Golzari, K., Singla, A., Zalozhin, D., Lohan, D., Farooq, M., Dede, E. M., & Kim, I. (2024). Optimization of stimulus properties for SSVEP-based BMI system with a heads-up display to control in-vehicle features. *PLOS ONE, 19*(9), e0308506. https://doi.org/10.1371/journal.pone.0308506

Malmivuo, J., & Plonsey, R. (1995). *Bioelectromagnetism: Principles and applications of bioelectric and biomagnetic fields*. Oxford University Press.
