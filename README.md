# Single-channel occipital EEG for a calculator BCI based on steady-state visual evoked potentials (SSVEP)

## Required components and downloads

* **EXG Pill by Upside Down Labs**. An instrumentation amplifier designed for recording small biopotential signals such as EEG, EMG, and ECG.

* **Arduino / Raspberry Pi / compatible microcontroller board**. Used to acquire the analog EEG signal from the EXG Pill and transmit the data to the computer.

* **EEG electrodes**. Adhesive electrodes (or preferably dry metal + conducting gel) electrodes positioned over the occipital region. In this project, O1 and O2 are used for the single differential EEG channel.

* **PsychoPy**. PsychoPy. This is used to generate precisely timed visual stimuli flickering at different frequencies, with each frequency corresponding to a different BCI command. The PsychoPy script also sends stimulus markers through Lab Streaming Layer (LSL), allowing MATLAB to synchronize the EEG with the presented frequencies during calibration and calculator use.

# Electrode placement

Electrode placement followed the international 10–20 system, with the recording electrode positioned at O1 or O2 over the occipital region. The approximate electrode locations can be seen in the figure below left (Malmivuo & Plonsey, 1995). The reference electrode was placed over the mastoid process behind the ear. 

<img width="500" height="260" alt="Screenshot 2026-09-10 185955" src="https://github.com/user-attachments/assets/46327836-8d41-4668-891e-65516f1de4aa" /> <img width="250" height="260" alt="image" src="https://github.com/user-attachments/assets/9d4c7b41-2dbd-446d-94d0-1484d58bf33b" />

# Stimulus production

Visual stimulation frequencies in approximately the 6–12 Hz range have been reported to produce relatively strong SSVEP responses, making them suitable for a low-channel-count EEG system (Hamidi Shishavan et al., 2024). The initial plan was to generate the flickering stimuli using PsychoPy. Frequencies of 6.67, 7.50, 8.57, and 10 Hz were tested because they correspond to an integer number of frames per cycle on a 60 Hz display (9, 8, 7, and 6 frames per cycle, respectively). In full-screen mode, the stimulus timing was sufficiently accurate; however, opening the full-screen PsychoPy window caused other applications involved in EEG recording, such as LabRecorder and LSL Connector, to lose their connections.

Running the stimulus in windowed mode prevented these disconnections, but the frame timing became unstable, with delays of approximately 10 ms affecting the actual frequencies. One possible solution would have been to use a separate computer for stimulus presentation. Another option considered was to continuously calculate the stimulus phase based on elapsed time and determine the required screen colour from the current phase. However, this would still be limited by the 60 Hz refresh rate. If a required colour transition occurred between two screen refreshes, the change could only be displayed at the next refresh, introducing a delay of up to 16.7 ms. The original PsychoPy stimulus design is shown on the lower left.

<img width="400" height="222" alt="Screenshot 2026-09-15 113300" src="https://github.com/user-attachments/assets/56910dfd-d5b0-4415-847f-8648f976600c" />

Using a second computer was unnecessarily complicated, as it would also have required synchronization between the stimulus computer and the EEG-recording computer using hardware triggers. I therefore the whole thing with Arduino-controlled LEDs, which were used to produce the visual stimulation frequencies for the SSVEP experiment. The Arduino provided more stable and unproblematic timing and was not limited by the 60 Hz monitor refresh rate, allowing whole-number stimulation frequencies to be used. The Arduino setup is shown in the upper-right image above, with three LEDs corresponding to three different stimulation frequencies (6, 8 and 10 Hz) and an OLED display indicating which LED to look at during calibration.


**Reference**

Hamidi Shishavan, H., Roy, R., Golzari, K., Singla, A., Zalozhin, D., Lohan, D., Farooq, M., Dede, E. M., & Kim, I. (2024). Optimization of stimulus properties for SSVEP-based BMI system with a heads-up display to control in-vehicle features. *PLOS ONE, 19*(9), e0308506. https://doi.org/10.1371/journal.pone.0308506

Malmivuo, J., & Plonsey, R. (1995). *Bioelectromagnetism: Principles and applications of bioelectric and biomagnetic fields*. Oxford University Press.
