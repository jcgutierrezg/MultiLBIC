* Laser board: the supply's passives, the enable and lid circuit, and
* channel 1, as on the schematic (docs/hardware/laser-board-schematic.md).
* Designators are the schematic's.
*
* The netlist that includes this file supplies:
*   a source on v5in   the SKR's 5 V at the connector
*   a source on v3     the analog 3.3 V
*   a source on dac    the DAC's output, 0 to 2.5 V (50 V per amp)
*   a source on en     GPIO21, 3.3 V = lasers enabled
*   the laser          between lasp (through the cable from v5) and drn
* and these parameters:
*   ACBRK, ACBRK2  1 only in the loop-gain run, otherwise 0
*   C105V  the capacitor across the module; 0 = not fitted
*   RLID   0.1 = lid shut, 1G = lid open
*   VTS, VTC  thresholds (models.lib)

* --- supply (sheet 1)
Rf1 v5in v5 0.6
C1 v5 0 330u Rser=0.15
C2 v5 0 10u Rser=5m

* --- enable and lid (sheet 1)
R7 v3 laser_off 10k
Xq1 laser_off eng lid CLAMPFET
R8 en eng 1k
R9 eng 0 100k
R12 v3 lid 100k
Rlid lid 0 {RLID}
* the gates of the other five clamps
Cgates laser_off 0 150p

* --- channel 1 (sheet 2)
R101 dac set 40.2k
R102 set 0 10k
C101 set 0 10n
Xq101 set laser_off 0 CLAMPFET
Xu2a set inn v3 0 oa OPAMP
R103 oa gate 3.9k
R104 gate 0 100k
Xq102 drn gate sns SINKFET
R105 sns 0 10
* sns and sfb are one node on the board: the second place the loop
* can be opened, for the outer loop alone: gain = -V(sfb)/V(sns).
Vbrk2 sns sfb dc 0 ac {ACBRK2}
R106 sfb fb 10k
C102 oa fb 1n
* fb and inn are one node on the board. This 0 V source is where the
* loop is opened for the loop-gain run: gain = -V(fb)/V(inn).
Vbrk fb inn dc 0 ac {ACBRK}
R107 sns adci 10k
C103 adci 0 100n
R108 drn adcv 1meg
R109 adcv 0 1meg
C104 adcv 0 100n
Xd101 drn v5 RDIODE
C105 v5 drn {C105V+1f}
