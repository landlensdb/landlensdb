
//python D:\tsutsumida\github\Mapillary_LCmodel\postgresql\count_image_region.py
//sum of IMAGEID (duplicated included): 51012
//sum of SEQID: 141
//sum of IMAGEID: 17726

select count(*) from mly_table;
select count(distinct imageid) from mly_table;
select count(distinct sequence) from mly_table;


select imageid, sequence from mly_table where imageid = 294454409011587;
select imageid from mly_table;

select * from yolov4_202207model;
select count(*) from yolov4_202207model;

select * from mly_table where imageid=290286379297915;
select * from yolov4_202207results;

select count(*) from fude;
select * from fude limit 3;