# Single-channel occipital EEG for a calculator BCI based on steady-state visual evoked potentials (SSVEP)

## Required components and downloads

* **EXG Pill by Upside Down Labs**. An instrumentation amplifier designed for recording small biopotential signals such as EEG, EMG, and ECG.

* **Arduino / Raspberry Pi / compatible microcontroller board**. Used to acquire the analog EEG signal from the EXG Pill and transmit the data to the computer.

* **EEG electrodes**. Adhesive electrodes (or preferably dry metal + conducting gel) electrodes positioned over the occipital region. In this project, O1 and O2 are used for the single differential EEG channel.

* **PsychoPy**. PsychoPy. This is used to generate precisely timed visual stimuli flickering at different frequencies, with each frequency corresponding to a different BCI command. The PsychoPy script also sends stimulus markers through Lab Streaming Layer (LSL), allowing MATLAB to synchronize the EEG with the presented frequencies during calibration and calculator use.

# Electrode placement

Electrode placement followed the international 10–20 system, with the recording electrode positioned at O1 or O2 over the occipital region. The approximate electrode locations can be seen in the figure below left (Malmivuo & Plonsey, 1995). The reference electrode was placed over the mastoid process behind the ear. 

<img width="500" height="260" alt="Screenshot 2026-09-10 185955" src="https://github.com/user-attachments/assets/46327836-8d41-4668-891e-65516f1de4aa" /> <img width="250" height="260" alt="image" src="https://github.com/user-attachments/assets/9d4c7b41-2dbd-446d-94d0-1484d58bf33b" />

# Stimulus frequency selection

Four visual stimulation frequencies (6.67, 7.50, 8.57, and 10.00 Hz) were selected for both calibration and the calculator BCI. Frequency selection was constrained by the 60 Hz monitor refresh rate because conventional frame-based visual stimulation can only generate frequencies corresponding to integer numbers of display frames per stimulation cycle. The selected frequencies correspond to 9, 8, 7, and 6 frames per cycle, respectively. Frequencies in approximately the 6–12 Hz range have also been reported to produce relatively strong SSVEP responses, making them suitable for a low-channel-count EEG system (Hamidi Shishavan et al., 2024).



**Reference**

Hamidi Shishavan, H., Roy, R., Golzari, K., Singla, A., Zalozhin, D., Lohan, D., Farooq, M., Dede, E. M., & Kim, I. (2024). Optimization of stimulus properties for SSVEP-based BMI system with a heads-up display to control in-vehicle features. *PLOS ONE, 19*(9), e0308506. https://doi.org/10.1371/journal.pone.0308506

Malmivuo, J., & Plonsey, R. (1995). *Bioelectromagnetism: Principles and applications of bioelectric and biomagnetic fields*. Oxford University Press.
