
# run insertdata_region.py in the background
#$job = Start-Job -scriptblock {& python D:\tsutsumida\github\Mapillary_LCmodel\postgresql\insertdata_region.py > D:\tsutsumida\github\Mapillary_LCmodel\postgresql\out.log}
$job = Start-Job -scriptblock {& python D:\tsutsumida\github\Mapillary_LCmodel\postgresql\insertdata_region.py}

# check job status
Get-Job 