from v2simux import AdvancedPlot
import sys

if __name__ == "__main__":
    from version_checker import check_requirements
    check_requirements()
    
    plt = AdvancedPlot()
    if len(sys.argv)>1:
        with open(sys.argv[1], "r") as f:
            command = f.readlines()
            plt.configure(command)
    else:
        print("Advanced Plotting Tool - Type 'help' for help")
        while True:
            print("> ", end="")
            ln = input()
            try:
                if not plt.configure(ln): break
            except Exception as e:
                print(e)
                continue