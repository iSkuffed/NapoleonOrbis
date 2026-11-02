// Disassembly of the functions containing the listed addresses.
//   tools/ghidra/run.sh Disasm.java OUTFILE ADDR [ADDR...]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;

public class Disasm extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        var out = new java.io.PrintWriter(a[0]);
        for (int i = 1; i < a.length; i++) {
            Function f = getFunctionContaining(toAddr(a[i]));
            out.println("---- " + a[i] + " " + (f == null ? "(no function)" : f.getName()));
            if (f == null) continue;
            for (Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                StringBuilder hex = new StringBuilder();
                for (byte b : ins.getBytes()) hex.append(String.format("%02x", b));
                out.println(ins.getAddress() + "  " + String.format("%-16s", hex) + " " + ins);
            }
        }
        out.close();
    }
}
