# Single-channel occipital EEG for a calculator BCI based on steady-state visual evoked potentials (SSVEP)

## Required components and downloads

* **EXG Pill by Upside Down Labs**. An instrumentation amplifier designed for recording small biopotential signals such as EEG, EMG, and ECG.

* **2x Arduino / Raspberry Pi / compatible microcontroller board**. One board is used to acquire the analog EEG signal from the EXG Pill and transmit the data to the computer. The second board is used to control the LEDs that generate the flickering visual stimuli.

# Electrode placement

Electrode placement followed the international 10–20 system, with the recording electrode positioned at O1 or O2 over the occipital region, where the visual processing takes place. The approximate electrode locations can be seen in the figure below left (Malmivuo & Plonsey, 1995). The reference electrode was placed over the mastoid process behind the ear. 

<img width="500" height="260" alt="Screenshot 2026-09-10 185955" src="https://github.com/user-attachments/assets/46327836-8d41-4668-891e-65516f1de4aa" /> <img width="250" height="260" alt="image" src="https://github.com/user-attachments/assets/9d4c7b41-2dbd-446d-94d0-1484d58bf33b" />

# SSVEP stimulus generation and timing

Visual stimulation frequencies in approximately the 6–12 Hz range have been reported to produce relatively strong SSVEP responses, making them suitable for a low-channel-count EEG system (Hamidi Shishavan et al., 2024). The initial plan was to generate the flickering stimuli using PsychoPy. Frequencies of 6.67, 7.50, 8.57, and 10 Hz were tested because they correspond to an integer number of frames per cycle on a 60 Hz display (9, 8, 7, and 6 frames per cycle, respectively). In full-screen mode, the stimulus timing was sufficiently accurate. However, opening the full-screen PsychoPy window caused applications involved in EEG recording, including LabRecorder and LSL Connector, to lose their connections. 

Running the stimulus in windowed mode prevented these disconnections, but the frame timing became unstable. Instead of the expected frame interval of approximately 16.7 ms, measured frame intervals were approximately 20–28 ms long. One possible solution would have been to use a separate computer for stimulus generation. Another option considered was to continuously calculate the stimulus phase from elapsed time and determine the required screen colour from the current phase. However, this method is also not reliable, because when a required colour transition occurs between two screen refreshes, it could only be displayed at the next refresh. The PsychoPy stimulus screen design is shown in the lower-left image.

<img width="400" height="222" alt="Screenshot 2026-09-15 113300" src="https://github.com/user-attachments/assets/56910dfd-d5b0-4415-847f-8648f976600c" />

Using a second computer was unnecessarily complicated, as it would also have required synchronization between the stimulus computer and the EEG-recording computer using hardware triggers. I therefore the whole thing with Arduino-controlled LEDs, which were used to produce the visual stimulation frequencies for the SSVEP experiment. The Arduino provided more stable and unproblematic timing and was not limited by the 60 Hz monitor refresh rate, allowing whole-number stimulation frequencies to be used. The very simple Arduino setup is shown in the upper-right image above, with three LEDs corresponding to three different stimulation frequencies (6, 8 and 10 Hz). 

During calibration, the participant is first shown which LED to look at. The selected LED remains continuously illuminated for one second as a cue before the flickering period begins. All three LEDs then start flickering at their respective frequencies, while the participant looks at the indicated LED for a predefined period. This is followed by a rest period before the next trial begins. At the start of each flickering period, the Arduino also sends a message to the computer indicating which stimulation frequency has started. MATLAB receives this message and sends a corresponding LSL marker, allowing the beginning of each calibration period to be identified later in the XDF recording.

## Calibration process and otsustamise design


## Real-time control of the calculator BCI


**Reference**

Hamidi Shishavan, H., Roy, R., Golzari, K., Singla, A., Zalozhin, D., Lohan, D., Farooq, M., Dede, E. M., & Kim, I. (2024). Optimization of stimulus properties for SSVEP-based BMI system with a heads-up display to control in-vehicle features. *PLOS ONE, 19*(9), e0308506. https://doi.org/10.1371/journal.pone.0308506

Malmivuo, J., & Plonsey, R. (1995). *Bioelectromagnetism: Principles and applications of bioelectric and biomagnetic fields*. Oxford University Press.
